"""Cross-modal (IR + depth) YOLOv5 fusion model used by the WOAD exp72 checkpoint.

Vendored from ``original/Cross-Modal obstacle detection/models/yolo.py``
(identical to ``yolo_fusion_v2.py``), YOLOv5 GPL-3.0.

What was kept unchanged (numerically identical):
  * Detect.forward / Detect._make_grid
  * myTransformerBlock, SelfAttention
  * Model.forward / Model._forward_once (the IR/depth fusion after backbone layer 2)

What was removed / changed (inference-irrelevant):
  * Model.__init__ / parse_model: the model is restored from the pickled
    checkpoint, so building from YAML is never needed here. Calling the
    constructor raises a clear error instead.
  * Test-time augmentation, profiling and feature visualisation hooks.
  * ``check_version(torch.__version__, '1.10.0')`` in _make_grid replaced by
    ``meshgrid(..., indexing='ij')``, which is what that branch executes on
    every supported torch version.
  * The unused, commented-out fusion experiments.

Fusion summary (backbone layer index 2, 1/4 resolution, 64 channels):
  ir, depth each scaled by a fixed 0.5 gate -> 8x8 avg-pooled tokens (2x64 tokens)
  -> + learned positional embedding -> 8 transformer blocks -> LayerNorm
  -> split back per modality, bilinearly upsampled to (H/4, W/4)
  -> each stream: (conv4 -> bn3 -> ReLU) x2, multiplied by its attention map
  -> concat -> conv3 -> bn3 -> ReLU -> rest of the YOLOv5s backbone/head.
"""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import init

from .common import Bottleneck, C3, Concat, Conv, SPPF  # noqa: F401  (needed for unpickling)


class Detect(nn.Module):
    stride = None  # strides computed during build
    onnx_dynamic = False  # ONNX export parameter

    def __init__(self, nc=80, anchors=(), ch=(), inplace=True):  # detection layer
        super().__init__()
        self.nc = nc  # number of classes
        self.no = nc + 5  # number of outputs per anchor
        self.nl = len(anchors)  # number of detection layers
        self.na = len(anchors[0]) // 2  # number of anchors
        self.grid = [torch.zeros(1)] * self.nl  # init grid
        self.anchor_grid = [torch.zeros(1)] * self.nl  # init anchor grid
        self.register_buffer('anchors', torch.tensor(anchors).float().view(self.nl, -1, 2))  # shape(nl,na,2)
        self.m = nn.ModuleList(nn.Conv2d(x, self.no * self.na, 1) for x in ch)  # output conv
        self.inplace = inplace  # use in-place ops (e.g. slice assignment)

    def forward(self, x):
        z = []  # inference output
        for i in range(self.nl):
            x[i] = self.m[i](x[i])  # conv
            bs, _, ny, nx = x[i].shape  # x(bs,255,20,20) to x(bs,3,20,20,85)
            x[i] = x[i].view(bs, self.na, self.no, ny, nx).permute(0, 1, 3, 4, 2).contiguous()

            if not self.training:  # inference
                if self.onnx_dynamic or self.grid[i].shape[2:4] != x[i].shape[2:4]:
                    self.grid[i], self.anchor_grid[i] = self._make_grid(nx, ny, i)

                y = x[i].sigmoid()
                if self.inplace:
                    y[..., 0:2] = (y[..., 0:2] * 2 - 0.5 + self.grid[i]) * self.stride[i]  # xy
                    y[..., 2:4] = (y[..., 2:4] * 2) ** 2 * self.anchor_grid[i]  # wh
                else:
                    xy = (y[..., 0:2] * 2 - 0.5 + self.grid[i]) * self.stride[i]  # xy
                    wh = (y[..., 2:4] * 2) ** 2 * self.anchor_grid[i]  # wh
                    y = torch.cat((xy, wh, y[..., 4:]), -1)
                z.append(y.view(bs, -1, self.no))

        return x if self.training else (torch.cat(z, 1), x)

    def _make_grid(self, nx=20, ny=20, i=0):
        d = self.anchors[i].device
        shape = 1, self.na, ny, nx, 2  # grid shape
        yv, xv = torch.meshgrid(torch.arange(ny, device=d), torch.arange(nx, device=d), indexing='ij')
        grid = torch.stack((xv, yv), 2).expand(shape).float()
        anchor_grid = (self.anchors[i] * self.stride[i]).view((1, self.na, 1, 1, 2)).expand(shape).float()
        return grid, anchor_grid


class myTransformerBlock(nn.Module):  # noqa: N801  (name fixed by the checkpoint pickle)
    """ Transformer block """

    def __init__(self, d_model, d_k, d_v, h, block_exp, attn_pdrop, resid_pdrop):
        super().__init__()
        self.ln_input = nn.LayerNorm(d_model)
        self.ln_output = nn.LayerNorm(d_model)
        self.sa = SelfAttention(d_model, d_k, d_v, h, attn_pdrop, resid_pdrop)
        self.mlp = nn.Sequential(
            nn.Linear(d_model, block_exp * d_model),
            nn.GELU(),
            nn.Linear(block_exp * d_model, d_model),
            nn.Dropout(resid_pdrop),
        )

    def forward(self, x):
        x = x + self.sa(self.ln_input(x))
        x = x + self.mlp(self.ln_output(x))
        return x


class SelfAttention(nn.Module):
    """ Multi-head self-attention layer """

    def __init__(self, d_model, d_k, d_v, h, attn_pdrop=.1, resid_pdrop=.1):
        super().__init__()
        assert d_k % h == 0
        self.d_model = d_model
        self.d_k = d_model // h
        self.d_v = d_model // h
        self.h = h
        self.que_proj = nn.Linear(d_model, h * self.d_k)  # query projection
        self.key_proj = nn.Linear(d_model, h * self.d_k)  # key projection
        self.val_proj = nn.Linear(d_model, h * self.d_v)  # value projection
        self.out_proj = nn.Linear(h * self.d_v, d_model)  # output projection
        self.attn_drop = nn.Dropout(attn_pdrop)
        self.resid_drop = nn.Dropout(resid_pdrop)
        self.init_weights()

    def init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                init.normal_(m.weight, std=0.001)
                if m.bias is not None:
                    init.constant_(m.bias, 0)

    def forward(self, x, attention_mask=None, attention_weights=None):
        b_s, nq = x.shape[:2]
        nk = x.shape[1]
        q = self.que_proj(x).view(b_s, nq, self.h, self.d_k).permute(0, 2, 1, 3)  # (b_s, h, nq, d_k)
        k = self.key_proj(x).view(b_s, nk, self.h, self.d_k).permute(0, 2, 3, 1)  # (b_s, h, d_k, nk) K^T
        v = self.val_proj(x).view(b_s, nk, self.h, self.d_v).permute(0, 2, 1, 3)  # (b_s, h, nk, d_v)

        att = torch.matmul(q, k) / np.sqrt(self.d_k)  # (b_s, h, nq, nk)
        if attention_weights is not None:
            att = att * attention_weights
        if attention_mask is not None:
            att = att.masked_fill(attention_mask, -np.inf)
        att = torch.softmax(att, -1)
        att = self.attn_drop(att)

        out = torch.matmul(att, v).permute(0, 2, 1, 3).contiguous().view(b_s, nq, self.h * self.d_v)
        out = self.resid_drop(self.out_proj(out))  # (b_s, nq, d_model)
        return out


class Model(nn.Module):
    """Two-stream IR + depth detector. Instances come only from the pickled checkpoint."""

    def __init__(self, *args, **kwargs):  # pragma: no cover
        raise RuntimeError(
            "woad.arch.yolo.Model cannot be built from YAML in this inference package; "
            "load it with woad.model_loader.load_model(). Use the original repository for training.")

    def forward(self, x, cloud, augment=False, profile=False, visualize=False):
        """x: IR image batch (B,3,H,W) in [0,1] RGB order; cloud: colour-mapped depth batch, same shape."""
        if augment or profile or visualize:
            raise NotImplementedError("augment/profile/visualize are not supported in the inference package")
        return self._forward_once(x, cloud)

    def _forward_once(self, x, cloud, profile=False, visualize=False):
        for i1, m1 in enumerate(self.model1):  # depth stem: Conv, Conv, C3 -> (B,64,H/4,W/4)
            cloud = m1(cloud)

        y = []  # outputs
        for i, m in enumerate(self.model):
            if m.f != -1:  # if not from previous layer
                x = y[m.f] if isinstance(m.f, int) else [x if j == -1 else y[j] for j in m.f]  # from earlier layers
            x = m(x)  # run
            y.append(x if m.i in self.save else None)  # save output
            if i == 2:
                bsz = cloud.shape[0]
                device = (torch.device('cuda') if cloud.is_cuda else torch.device('cpu'))
                init_score = np.array([0.5, 0.5])
                guide_score = np.repeat(init_score, bsz, axis=0).reshape(2, bsz).transpose(1, 0).astype(np.float32)
                guide_score = torch.tensor(guide_score).to(device)
                new_score = F.normalize(guide_score, p=1, dim=1).float()
                x = x * (new_score[:, 0].view(-1, 1, 1, 1))
                cloud = cloud * (new_score[:, 1].view(-1, 1, 1, 1))

                bs, c, h, w = x.shape
                x_fea = self.avp(x)
                cloud_fea = self.avp(cloud)
                x_fea_flat = x_fea.view(bs, c, -1)
                cloud_fea_flat = cloud_fea.view(bs, c, -1)

                token_embeddings = torch.cat([x_fea_flat, cloud_fea_flat], dim=2)  # concat
                token_embeddings = token_embeddings.permute(0, 2, 1).contiguous()  # (B, 2*H*W, C)
                x_fusion = self.drop(self.pos_emb + token_embeddings)
                x_fusion = self.trans_blocks(x_fusion)
                x_fusion = self.norm(x_fusion)
                x_fusion = x_fusion.view(bs, 2, 8, 8, 64)
                x_fusion = x_fusion.permute(0, 1, 4, 2, 3)  # (B, 2, C, H, W)

                x_fea_out = x_fusion[:, 0, :, :, :].contiguous().view(bs, 64, 8, 8)
                cloud_fea_out = x_fusion[:, 1, :, :, :].contiguous().view(bs, 64, 8, 8)
                x_fea_out = F.interpolate(x_fea_out, size=([h, w]), mode='bilinear')
                cloud_fea_out = F.interpolate(cloud_fea_out, size=([h, w]), mode='bilinear')

                x = self.conv4(x)
                x = self.bn3(x)
                x = self.relu(x)
                x = self.conv4(x)
                x = self.bn3(x)
                x = self.relu(x)
                x = x * x_fea_out

                cloud = self.conv4(cloud)
                cloud = self.bn3(cloud)
                cloud = self.relu(cloud)
                cloud = self.conv4(cloud)
                cloud = self.bn3(cloud)
                cloud = self.relu(cloud)
                cloud = cloud * cloud_fea_out
                x = torch.cat([x, cloud], 1)
                x = self.conv3(x)
                x = self.bn3(x)
                x = self.relu(x)
        return x
