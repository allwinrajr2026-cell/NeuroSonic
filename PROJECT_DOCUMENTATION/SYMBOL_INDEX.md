# Symbol index (generated from the source code)

Generated 2026-11-03 02:15 by parsing every Python file with `ast` and every JavaScript file with a line scanner.
Line ranges are `L<first>–<last>` (Python) or `L<first>` (JavaScript). Regenerate after code changes; every line number quoted in this documentation was taken from this index.

### `experiments/ir_brightness_test.py` (197 lines)
- const `ROOT` L30
- const `TRANSFORMS` L35
- def `pooled_cdf` L38–43
- def `match_to_cdf` L46–50
- def `transform` L53–66
- def `iou` L69–73
- def `agreement` L76–89
- def `stats` L92–93
- def `main` L96–193

### `neurosonic/__init__.py` (2 lines)

### `neurosonic/awareness.py` (278 lines)
- const `ROOT` L38
- const `DEFAULT_WEIGHTS` L39
- const `OBSTACLE_CLASSES` L42
- const `MODES` L51
- const `URGENT_AREA` L55
- const `SESSION_IDLE_S` L56
- const `DETECTOR_INFO` L59
- class `_Session` L67–76
  - `_Session.__init__` L70–76
- class `RGBAwareness` L79–278
  - `RGBAwareness.__init__` L80–99
  - `RGBAwareness.available` L102–106
  - `RGBAwareness.detector_name` L108–109
  - `RGBAwareness.info` L111–132
  - `RGBAwareness._load` L134–142
  - `RGBAwareness.warm_up` L144–150
  - `RGBAwareness.detect` L153–157
  - `RGBAwareness._detect_on_worker` L159–168
  - `RGBAwareness.quality` L171–178
  - `RGBAwareness._engine` L181–182
  - `RGBAwareness._session` L184–187
  - `RGBAwareness._state` L189–203
  - `RGBAwareness.process_frame` L205–278

### `neurosonic/detectors.py` (185 lines)
- const `ROOT` L25
- const `SSDLITE_WEIGHTS` L26
- const `RFDETR_WEIGHT_CANDIDATES` L27
- const `DETECTOR_ENV` L29
- const `GPU_MODE_CPU_THREADS` L33
- class `DetectorUnavailable` L36–37
- def `_filter` L40–48
- class `SSDLiteDetector` L51–77
  - `SSDLiteDetector.__init__` L54–59
  - `SSDLiteDetector._load` L61–67
  - `SSDLiteDetector.detect` L69–77
- def `find_rfdetr_weights` L80–84
- class `RFDETRDetector` L87–122
  - `RFDETRDetector.__init__` L90–117
  - `RFDETRDetector.detect` L119–122
- class `FallbackDetector` L125–158
  - `FallbackDetector.__init__` L128–133
  - `FallbackDetector.name` L136–137
  - `FallbackDetector.device` L140–141
  - `FallbackDetector.input_size` L144–145
  - `FallbackDetector.detect` L147–158
- def `make_detector` L161–185

### `neurosonic/events.py` (132 lines)
- const `MIN_HITS` L21
- const `MIN_AGE_S` L22
- const `WINDOW_S` L23
- const `CROSS_WINDOW_S` L24
- const `ENTER_SPEED` L25
- const `CROSS_SPEED` L26
- const `MAX_CAM_SHIFT` L27
- const `MAX_CAM_SCALE` L28
- const `GLOBAL_GAP_S` L29
- const `MOVERS` L30
- def `_article` L33–35
- def `_text` L38–45
- class `PathEventDetector` L48–132
  - `PathEventDetector.__init__` L49–52
  - `PathEventDetector._camera_stable` L54–57
  - `PathEventDetector.update` L59–76
  - `PathEventDetector._window` L78–79
  - `PathEventDetector._rel_speed_x` L81–85
  - `PathEventDetector._entering` L87–110
  - `PathEventDetector._crossing` L112–132

### `neurosonic/maps.py` (313 lines)
- const `WALK_SPEED_MPS` L16
- const `MAX_SNAP_M` L17
- const `MAX_ISLAND_SNAP_M` L18
- const `MAJOR` L19
- class `MapError` L22–23
- def `haversine` L26–31
- def `bearing` L34–38
- def `turn_word` L41–51
- def `fmt_m` L54–55
- class `OfflineMap` L58–313
  - `OfflineMap.__init__` L59–90
  - `OfflineMap.info` L93–97
  - `OfflineMap.in_coverage` L99–101
  - `OfflineMap.nearest_node` L103–108
  - `OfflineMap.search` L111–137
  - `OfflineMap.route` L140–182
  - `OfflineMap._astar` L184–205
  - `OfflineMap._point_at` L213–220
  - `OfflineMap._steps` L222–313

### `neurosonic/netcheck.py` (68 lines)
- const `RULE_NAME` L15
- def `_ps` L18–21
- def `windows_report` L24–57
- def `print_report` L60–68

### `neurosonic/pathguide.py` (221 lines)
- const `SEVERITY` L31
- const `CATEGORY` L33
- const `MESSAGES` L36
- const `REMINDER` L53
- const `PATH_POLYGON` L57
- def `_path_mask` L61–65
- const `PATH_MASK` L68
- const `PATH_CELLS` L69
- class `Thresholds` L73–82
- def `sharpness` L85–90
- def `box_path_overlap` L93–101
- def `side_of` L104–106
- class `FrameAssessment` L110–116
- def `assess_frame` L119–154
- class `PathGuide` L157–221
  - `PathGuide.__init__` L160–170
  - `PathGuide._decide` L172–185
  - `PathGuide._signature` L188–189
  - `PathGuide.update` L191–218
  - `PathGuide.camera_unavailable` L220–221

### `neurosonic/server.py` (538 lines)
- const `WEB_ROOT` L45
- const `MAX_BODY` L46
- const `TLS_HANDSHAKE_TIMEOUT` L47
- const `REQUEST_TIMEOUT` L48
- const `STATIC_TYPES` L49
- const `CLIENT_SOURCES` L52
- const `CLIENT_KINDS` L53
- class `ApiError` L56–59
  - `ApiError.__init__` L57–59
- def `make_handler` L62–413
  - nested class `Handler` L66–411
    - `Handler.log_message` L70–72
    - `Handler._send` L75–86
    - `Handler._json` L88–89
    - `Handler._raw_body` L91–101
    - `Handler._body` L103–115
    - `Handler._drain_unread_body` L117–131
    - `Handler._dispatch` L133–159
    - `Handler._static` L161–169
    - `Handler.r_status` L172–175
    - `Handler.r_events` L177–183
    - `Handler.r_replay_start` L185–188
    - `Handler.r_replay_stop` L190–192
    - `Handler.r_replay_state` L194–195
    - `Handler.r_replay_frame` L197–201
    - `Handler.r_detect` L203–210
    - `Handler.r_alerts` L212–218
    - `Handler.r_history` L220–222
    - `Handler.r_history_clear` L224–227
    - `Handler.r_stats` L229–230
    - `Handler.r_places` L232–237
    - `Handler.r_places_delete` L239–243
    - `Handler.r_tts_status` L246–247
    - `Handler.r_tts` L249–253
    - `Handler._send_media` L255–272
    - `Handler.r_voice_report` L274–287
    - `Handler.r_voice_reports` L289–290
    - `Handler._map` L293–296
    - `Handler.r_map_info` L298–299
    - `Handler.r_map_data` L301–309
    - `Handler.r_map_search` L311–316
    - `Handler.r_route` L318–325
    - `Handler.r_voicecmd_status` L328–329
    - `Handler.r_voicecmd` L331–346
    - `Handler.r_vision_status` L350–354
    - `Handler.r_vision_describe` L356–372
    - `Handler.r_awareness_status` L374–375
    - `Handler.r_awareness_frame` L377–390
    - `Handler.do_GET` L404–405
    - `Handler.do_HEAD` L407–408
    - `Handler.do_POST` L410–411
- def `_strip_data_url` L416–418
- class `NeuroSonicHTTPServer` L421–459
  - `NeuroSonicHTTPServer.server_bind` L435–438
  - `NeuroSonicHTTPServer.__init__` L440–442
  - `NeuroSonicHTTPServer.finish_request` L444–459
- def `make_server` L462–466
- def `make_setup_server` L469–506
  - nested class `SetupHandler` L475–504
    - `SetupHandler.log_message` L479–481
    - `SetupHandler._send` L483–492
    - `SetupHandler.do_GET` L494–502
- const `SETUP_PAGE` L509
- def `serve_in_thread` L535–538

### `neurosonic/service.py` (234 lines)
- const `ROOT` L25
- const `REPLAY_SETS` L27
- class `InvalidInput` L37–38
- def `decode_image` L41–56
- def `render` L59–65
- class `EventLog` L68–96
  - `EventLog.__init__` L71–75
  - `EventLog.add` L77–87
  - `EventLog.since` L89–91
  - `EventLog.last_id` L94–96
- class `ReplayRunner` L99–161
  - `ReplayRunner.__init__` L100–111
  - `ReplayRunner.stop` L113–114
  - `ReplayRunner._publish` L116–118
  - `ReplayRunner.snapshot` L120–122
  - `ReplayRunner.run` L124–161
- class `DetectionService` L164–234
  - `DetectionService.__init__` L165–171
  - `DetectionService.info` L173–176
  - `DetectionService.replay_sets` L179–181
  - `DetectionService.start_replay` L184–195
  - `DetectionService.stop_replay` L197–202
  - `DetectionService.replay_state` L204–207
  - `DetectionService.replay_jpeg` L209–210
  - `DetectionService.detect_upload` L213–234

### `neurosonic/store.py` (103 lines)
- const `SCHEMA` L6
- const `ALLOWED_SOURCES` L28
- const `ALLOWED_KINDS` L29
- class `Store` L32–103
  - `Store.__init__` L33–40
  - `Store.close` L42–44
  - `Store.add_alert` L47–58
  - `Store.history` L60–64
  - `Store.stats` L66–74
  - `Store.clear_history` L76–79
  - `Store.add_place` L82–93
  - `Store.places` L95–97
  - `Store.delete_place` L99–103

### `neurosonic/tls.py` (137 lines)
- const `CA_NAME` L27
- const `SERVER_DAYS` L28
- const `CA_DAYS` L29
- class `TLSSetupError` L32–33
- def `lan_ips` L36–55
- def `_openssl` L58–65
- def `_run` L68–72
- def `fingerprint_sha256` L75–78
- def `_not_after` L81–83
- def `ensure_certificates` L86–130
- def `server_ssl_context` L133–137

### `neurosonic/tracking.py` (161 lines)
- class `CameraMotion` L23–38
  - `CameraMotion.apply` L31–34
  - `CameraMotion.as_dict` L36–38
- def `estimate_camera_motion` L41–64
- def `small_gray` L67–71
- def `iou` L75–79
- class `Track` L83–102
  - `Track.age` L97–98
  - `Track.as_dict` L100–102
- class `ByteTracker` L105–161
  - `ByteTracker.__init__` L106–109
  - `ByteTracker._associate` L111–123
  - `ByteTracker.update` L125–161

### `neurosonic/tts.py` (154 lines)
- const `ROOT` L17
- const `DEFAULT_VOICE` L18
- const `MAX_CHARS` L19
- const `CACHE_FILES` L20
- const `STYLE` L24
- class `TTSError` L27–28
- class `PiperTTS` L31–141
  - `PiperTTS.__init__` L32–40
  - `PiperTTS.info` L43–52
  - `PiperTTS.available` L54–63
  - `PiperTTS._load` L65–73
  - `PiperTTS.warm_up` L75–83
  - `PiperTTS.clean` L87–93
  - `PiperTTS.synthesize` L95–130
  - `PiperTTS._syn_config` L132–136
  - `PiperTTS._trim_cache` L138–141
- def `_piper_version` L144–149
- def `wav_duration` L152–154

### `neurosonic/voicecmd.py` (241 lines)
- const `ROOT` L21
- const `DEFAULT_MODEL` L22
- const `MAX_SECONDS` L23
- const `COMMAND_WORDS` L24
- const `HELP_TEXT` L30
- class `VoiceCommandError` L35–36
- const `_SPELLED` L40
- const `_STOP` L42
- def `phonetic` L45–59
- def `place_score` L62–71
- def `parse_intent` L74–124
- def `read_wav16k` L127–138
- class `VoiceCommands` L141–241
  - `VoiceCommands.__init__` L142–148
  - `VoiceCommands.available` L150–159
  - `VoiceCommands.info` L161–163
  - `VoiceCommands._load` L165–174
  - `VoiceCommands.warm_up` L176–182
  - `VoiceCommands.transcribe` L184–196
  - `VoiceCommands.resolve_place` L199–222
  - `VoiceCommands.handle` L224–241

### `neurosonic_app.py` (160 lines)
- const `ROOT` L16
- def `main` L28–156

### `tools/benchmark_detectors.py` (285 lines)
- const `ROOT` L35
- const `DATA` L39
- const `VAL_IMAGES` L40
- const `VAL_LABELS` L41
- const `SEQ` L42
- const `STREET` L43
- const `SSDLITE_WEIGHTS` L44
- const `WEIGHTS_DIR` L45
- const `PROD_THRESHOLD` L46
- const `COCO_PERSON_NAME` L47
- class `Detector` L51–54
- class `SSDLite` L57–74
  - `SSDLite.__init__` L58–67
  - `SSDLite.predict` L70–74
- class `RFDETR` L77–98
  - `RFDETR.__init__` L78–92
  - `RFDETR.predict` L94–98
- class `YOLO26` L101–118
  - `YOLO26.__init__` L102–113
  - `YOLO26.predict` L115–118
- def `make` L121–128
- def `sync` L132–134
- def `nvidia_used_mib` L137–143
- def `read_labels` L146–154
- def `evaluate_quality` L157–190
- def `evaluate_speed` L193–236
- def `street_detections` L239–244
- def `main` L247–281

### `tools/benchmark_precision.py` (100 lines)
- const `ROOT` L21
- class `Wrapped` L28–46
  - `Wrapped.__init__` L31–40
  - `Wrapped.predict` L42–46
- def `gpu_clock` L49–55
- def `speed` L58–71
- def `main` L74–96

### `tools/build_offline_map.py` (206 lines)
- const `ROOT` L25
- const `EXCLUDED_HIGHWAYS` L26
- const `MAJOR` L27
- const `ROAD_CLASS` L28
- def `haversine` L35–40
- def `sha256` L43–48
- def `walkable` L51–58
- def `load` L61–65
- def `r6` L68–69
- def `build` L72–190
- def `main` L193–202

### `tools/evaluate.py` (280 lines)
- const `ROOT` L34
- def `parse_class_map` L45–60
- def `read_labels` L63–80
- def `evaluate` L83–185
- def `main` L188–276

### `tools/make_e2e_media.py` (45 lines)
- const `ROOT` L17
- def `main` L23–41

### `tools/make_event_clip.py` (50 lines)
- const `ROOT` L16
- const `IR` L17
- def `main` L20–46

### `tools/make_golden.py` (37 lines)
- const `ROOT` L16
- const `DEMO` L21
- const `OUT` L22
- const `FRAMES` L23
- def `main` L26–33

### `tools/make_publication_figures.py` (189 lines)
- const `ROOT` L15
- const `OUT` L16
- const `NAMES` L19
- def `bench` L23–31
- def `fig_latency` L34–49
- def `fig_accuracy` L52–70
- def `fig_cpu_threads` L73–85
- def `fig_soak` L88–115
- def `box` L118–120
- def `arrow` L123–126
- def `fig_architecture` L129–156
- def `fig_pipeline` L159–178

### `tools/prepare_detec_test_demo.py` (78 lines)
- const `ROOT` L19
- const `DRIVE_ID` L25
- const `ARCHIVE_SHA256` L26
- def `sha256` L29–34
- def `main` L37–74

### `tools/reconstruct_val_samples.py` (136 lines)
- const `ROOT` L30
- const `DEFAULT_SRC` L31
- const `DEFAULT_OUT` L32
- const `CHROMA_THR` L35
- def `overlay_mask` L38–47
- def `compose` L50–58
- def `tile_slice` L61–64
- def `main` L67–132

### `tools/soak_test.py` (128 lines)
- def `read_y4m` L26–36
- def `gpu` L39–45
- def `main` L48–124

### `tools/verify_equivalence.py` (76 lines)
- const `ROOT` L21
- const `DEFAULT_ORIGINAL` L23
- const `ORIGINAL_SNIPPET` L25
- def `make_inputs` L40–42
- def `run` L45–67

### `woad/__init__.py` (2 lines)

### `woad/alerts.py` (249 lines)
- const `SPOKEN` L26
- const `POSITION_TEXT` L27
- class `AlertConfig` L33–62
  - `AlertConfig.validate` L53–62
- class `AlertEvent` L66–77
  - `AlertEvent.as_dict` L75–77
- class `_Track` L80–88
  - `_Track.__init__` L83–88
- def `_iou` L91–96
- class `AlertEngine` L99–249
  - `AlertEngine.__init__` L100–110
  - `AlertEngine._bucket` L113–115
  - `AlertEngine._reset_tracking` L117–119
  - `AlertEngine._system` L121–122
  - `AlertEngine._go_unavailable` L124–129
  - `AlertEngine.tick` L132–137
  - `AlertEngine.process` L140–249

### `woad/arch/__init__.py` (1 lines)

### `woad/arch/common.py` (89 lines)
- def `autopad` L15–19
- class `Conv` L22–34
  - `Conv.__init__` L24–28
  - `Conv.forward` L30–31
  - `Conv.forward_fuse` L33–34
- class `Bottleneck` L37–47
  - `Bottleneck.__init__` L39–44
  - `Bottleneck.forward` L46–47
- class `C3` L50–61
  - `C3.__init__` L52–58
  - `C3.forward` L60–61
- class `SPPF` L64–79
  - `SPPF.__init__` L66–71
  - `SPPF.forward` L73–79
- class `Concat` L82–89
  - `Concat.__init__` L84–86
  - `Concat.forward` L88–89

### `woad/arch/yolo.py` (223 lines)
- class `Detect` L37–82
  - `Detect.__init__` L41–51
  - `Detect.forward` L53–74
  - `Detect._make_grid` L76–82
- class `myTransformerBlock` L85–103
  - `myTransformerBlock.__init__` L88–98
  - `myTransformerBlock.forward` L100–103
- class `SelfAttention` L106–148
  - `SelfAttention.__init__` L109–122
  - `SelfAttention.init_weights` L124–129
  - `SelfAttention.forward` L131–148
- class `Model` L151–223
  - `Model.__init__` L154–157
  - `Model.forward` L159–163
  - `Model._forward_once` L165–223

### `woad/detector.py` (88 lines)
- class `WOADDetector` L12–88
  - `WOADDetector.__init__` L20–31
  - `WOADDetector._class_id` L33–42
  - `WOADDetector.raw_forward` L45–47
  - `WOADDetector.detect_prepared` L49–72
  - `WOADDetector.detect_arrays` L74–75
  - `WOADDetector.detect_files` L77–84
  - `WOADDetector.settings` L86–88

### `woad/metrics.py` (110 lines)
- const `IOUV` L13
- def `process_batch` L16–29
- def `compute_ap` L32–38
- def `ap_per_class` L41–72
- class `ConfusionMatrix` L75–110
  - `ConfusionMatrix.__init__` L78–80
  - `ConfusionMatrix.process_batch` L82–110

### `woad/model_loader.py` (130 lines)
- const `ROOT` L20
- const `DEFAULT_WEIGHTS` L21
- const `EXP72_BEST_SHA256` L24
- const `EXPECTED_NAMES` L25
- const `EXPECTED_CHILDREN` L26
- class `CheckpointError` L30–31
- def `sha256` L34–42
- def `_legacy_module_aliases` L46–61
- def `select_device` L64–73
- def `load_model` L76–130

### `woad/ops.py` (186 lines)
- def `letterbox` L21–51
- def `xywh2xyxy` L54–61
- def `box_iou` L64–71
- def `non_max_suppression` L74–158
- def `scale_coords` L161–174
- def `clip_coords` L177–186

### `woad/pairing.py` (88 lines)
- class `PairingError` L13–14
- class `PairingResult` L18–35
  - `PairingResult.complete` L24–25
  - `PairingResult.describe_missing` L27–35
- def `_list_images` L38–39
- def `_key` L42–43
- def `pair_directories` L46–77
- def `resolve_source_root` L80–88

### `woad/preprocess.py` (100 lines)
- const `IMG_SIZE` L28
- const `IMG_EXTS` L29
- class `InputImageError` L32–33
- def `read_image` L36–53
- def `_to_tensor` L56–59
- def `preprocess_ir` L62–69
- def `preprocess_depth` L72–75
- class `PreparedPair` L79–84
- def `prepare_pair` L87–96
- def `load_pair` L99–100

### `woad/quality.py` (82 lines)
- const `_RANK` L24
- class `QualityThresholds` L28–33
- class `QualityReport` L37–48
  - `QualityReport.as_dict` L44–48
- class `InputQualityChecker` L51–82
  - `InputQualityChecker.__init__` L52–53
  - `InputQualityChecker.check` L55–82

### `woad/replay.py` (45 lines)
- def `run_replay` L7–34
- def `load_cached_detections` L37–45

### `woad/sources.py` (88 lines)
- const `_DIGITS` L21
- class `Frame` L25–34
- def `_number` L37–39
- class `ReplaySource` L42–88
  - `ReplaySource.__init__` L43–52
  - `ReplaySource.from_root` L55–57
  - `ReplaySource.__len__` L59–60
  - `ReplaySource.describe` L62–64
  - `ReplaySource.__iter__` L66–88

### `woad/visualize.py` (43 lines)
- const `_HEX` L5
- def `color_bgr` L8–11
- def `draw_detections` L14–29
- def `side_by_side` L32–43

### `woad_detect.py` (173 lines)
- const `ROOT` L27
- def `parse_args` L43–79
- def `collect_pairs` L82–95
- def `increment_dir` L98–105
- def `main` L108–169

### `woad_replay.py` (136 lines)
- const `ROOT` L25
- def `parse_args` L38–71
- def `main` L74–132

### `web/js/app.js` (1015 lines)
- const `escapeHtml` L8
- section: settings + voice L10
- const `DEFAULTS` L13
- const `settings` L14
- const `saveSettings` L15
- const `voice` L16
- function `showAlert` L18
- function `badge` L29
- function `pill` L30
- function `api` L32
- const `logClientAlert` L39
- section: screens L42
- function `showTab` L43
- section: server / network status L60
- const `status` L61
- function `updateNet` L62
- function `init` L66
- function `pollEvents` L88
- section: WOAD replay (research tools) L106
- handler `#r-start.onclick` L108
- handler `#r-stop.onclick` L115
- function `pollReplay` L117
- section: single pair upload (research tools) L137
- const `readB64` L138
- handler `#u-go.onclick` L140
- section: GPS L153
- function `geoStatus` L157
- const `usableFix` L158
- function `renderGps` L160
- function `startLocation` L173
- function `stopLocation` L182
- function `onGeoError` L188
- handler `#g-start.onclick` L201
- handler `#g-stop.onclick` L202
- function `onFix` L204
- function `onPosition` L219
- section: saved places + straight-line fallback L232
- function `loadPlaces` L233
- handler `#p-go.onclick` L239
- handler `#p-clear.onclick` L248
- handler `#p-save-here.onclick` L252
- handler `#p-save-coords.onclick` L257
- function `savePlace` L262
- handler `#p-delete.onclick` L268
- function `updateGuidance` L273
- section: offline map, search, walking route L287
- const `mapView` L288
- const `curPos` L290
- function `loadMap` L292
- function `updateCoverage` L308
- handler `#m-zoom-in.onclick` L316
- handler `#m-zoom-out.onclick` L317
- handler `#m-fit.onclick` L318
- handler `#m-me.onclick` L319
- function `runSearch` L326
- handler `#s-go.onclick` L339
- function `chooseDestination` L342
- function `planRoute` L353
- handler `#rt-plan.onclick` L383
- handler `#rt-start.onclick` L384
- function `stopGuidance` L393
- handler `#rt-stop.onclick` L399
- function `followActiveRoute` L402
- handler `#sim-here.onclick` L422
- handler `#sim-off.onclick` L423
- handler `#sim-step.onclick` L424
- section: event-camera simulation (research tools) L436
- const `alerter` L438
- const `work` L439
- const `wctx` L440
- handler `#s-th.oninput` L441
- handler `#s-start.onclick` L442
- handler `#s-stop.onclick` L458
- const `simCtx` L463
- const `simOut` L464
- function `simStep` L465
- section: history L481
- function `fmtTime` L482
- function `loadHistory` L486
- handler `#h-refresh.onclick` L495
- handler `#h-clear.onclick` L496
- section: live camera awareness: Walking Guidance L498
- const `PATH_UI` L501
- const `FRAME_MS_DEFAULT` L510
- const `frameMs` L511
- const `aLatency` L512
- const `aCanvas` L515
- function `renderDetector` L518
- function `setPathState` L525
- function `cameraUnavailable` L532
- function `startAwareness` L541
- function `stopAwareness` L567
- function `scheduleFrame` L578
- function `awarenessStep` L580
- function `drawAwareness` L638
- handler `#a-start.onclick` L661
- handler `#a-stop.onclick` L662
- function `setDescribe` L668
- handler `#od-walk.onclick` L676
- handler `#od-desc.onclick` L677
- handler `#v-describe.onchange` L678
- section: online scene description (cloud, opt-in) L680
- const `STILL_MAX` L685
- const `SCENE_REQUEST_TIMEOUT_MS` L688
- const `SCENE_STILL_WAITING_MS` L689
- const `SCENE_STILL_WAITING_TEXT` L690
- function `renderVision` L691
- function `checkVision` L705
- function `setCloudConsent` L709
- function `captureStill` L716
- function `describeScene` L737
- handler `#sc-go.onclick` L777
- handler `#sc-allow.onclick` L779
- handler `#sc-deny.onclick` L780
- handler `#v-cloud.onchange` L781
- section: spoken status report L783
- function `statusReport` L784
- section: voice commands (push-to-talk, offline Vosk on the laptop) L803
- const `micLabel` L805
- function `checkVoiceCommands` L806
- function `listenOnce` L817
- function `runIntent` L842
- handler `#mic.onclick` L880
- section: permissions + offline status (Settings) L882
- const `PERM_TEXT` L883
- function `checkPermissions` L884
- function `askMedia` L893
- handler `#perm-ask-cam.onclick` L903
- handler `#perm-ask-mic.onclick` L904
- handler `#perm-ask-loc.onclick` L905
- function `renderOffline` L911
- section: settings UI L926
- function `fillVoices` L927
- function `updateVoiceBadge` L934
- function `checkVoiceEngine` L953
- handler `#v-engine.onchange` L968
- handler `#v-mode.onchange` L970
- handler `#v-speech.onchange` L977
- handler `#v-beeps.onchange` L978
- handler `#v-voice.onchange` L979
- handler `#v-rate.onchange` L980
- handler `#v-vol.onchange` L981
- handler `#v-test.onclick` L982

### `web/js/eventsim.js` (67 lines)
- function `toGray` L5
- function `diffEvents` L12
- const `NAMES` L28
- const `TEXT` L29
- class `MotionAlerter` L32
  - `MotionAlerter.constructor` L33
  - `MotionAlerter.update` L40
- function `paintEvents` L62

### `web/js/mapview.js` (204 lines)
- const `M_PER_DEG_LAT` L4
- const `M_PER_DEG_LON` L5
- class `MapView` L7
  - `MapView.constructor` L8
  - `MapView.setData` L26
  - `MapView.inCoverage` L32
  - `MapView.fitBounds` L36
  - `MapView.setPosition` L43
  - `MapView.setFollow` L53
  - `MapView.setDestination` L54
  - `MapView.setRoute` L55
  - `MapView.centerOn` L64
  - `MapView.zoom` L65
  - `MapView._xy` L68
  - `MapView._ll` L73
  - `MapView._bind` L80
  - `MapView._refit` L114
  - `MapView.shown` L119
  - `MapView.resize` L120
  - `MapView.redraw` L129
  - `MapView._path` L136
  - `MapView._draw` L145
  - `MapView._label` L196

### `web/js/nav.js` (200 lines)
- const `R` L3
- const `rad` L4
- const `deg` L5
- function `distanceM` L7
- function `bearingDeg` L13
- const `COMPASS` L19
- function `compass` L20
- function `formatDistance` L24
- function `parseCoords` L30
- const `acc` L38
- function `guidance` L42
- section: following an offline route L65
- function `toXY` L67
- function `projectOnPolyline` L73
- function `pointAtAlong` L90
- function `prepareRoute` L108
- function `followRoute` L116
- function `osmWalkingUrl` L161
- section: GPS fix quality (pure; unit-tested) L165
- const `GPS_LIMITS` L168
- function `assessFix` L169
- function `gpsWatch` L188
- function `canReroute` L198

### `web/js/recorder.js` (100 lines)
- const `TARGET_RATE` L5
- const `MAX_S` L6
- function `downsample` L9
- function `encodeWav` L21
- function `rms` L34
- class `EndOfSpeech` L42
  - `EndOfSpeech.constructor` L43
  - `EndOfSpeech.push` L48
- function `recordUtterance` L65

### `web/js/speech.js` (287 lines)
- const `PRIORITY` L4
- const `MAX_AGE_MS` L8
- const `COOLDOWN_MS` L10
- const `GAP_MS` L12
- const `INTERRUPTING` L14
- const `TEST_SENTENCE` L16
- class `SpeechQueue` L18
  - `SpeechQueue.constructor` L20
  - `SpeechQueue.cooldown` L27
  - `SpeechQueue.push` L34
  - `SpeechQueue.next` L47
  - `SpeechQueue.clear` L58
  - `SpeechQueue.shouldInterrupt` L61
  - `SpeechQueue.requeue` L68
- function `panFor` L77
- function `silentWavBytes` L82
- class `Announcer` L93
  - `Announcer.constructor` L94
  - `Announcer.voices` L111
  - `Announcer.canSpeak` L112
  - `Announcer._setStatus` L114
  - `Announcer.unlock` L118
  - `Announcer.beep` L137
  - `Announcer.say` L156
  - `Announcer.interrupt` L168
  - `Announcer._pump` L174
  - `Announcer.prefetch` L211
  - `Announcer._neuralUrl` L216
  - `Announcer._playNeural` L233
  - `Announcer._playBrowser` L260
  - `Announcer.stop` L280
