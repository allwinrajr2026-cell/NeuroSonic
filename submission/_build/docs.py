"""Document specifications: which fragments go into which PDF."""

AUTHORS = """<div class="authors"><div class="a"><div class="name">Allwin Raj</div>
<div>Vellore Institute of Technology</div><div>Vellore, Tamil Nadu, India</div><div>theallwinraj@gmail.com</div></div></div>"""

KW = ("assistive technology; visual impairment; electronic travel aid; obstacle detection; RF-DETR; multi-object "
      "tracking; camera-motion compensation; offline speech; pedestrian navigation")


def abstract(text, kw=KW):
    return (f'<p class="abstract ni"><span class="lbl">Abstract</span>&mdash;{text}</p>'
            f'<p class="keywords ni"><span class="lbl">Index Terms</span>&mdash;{kw}</p>')


ABS_DA1 = abstract(
    "This review surveys assistive technology for pedestrians with visual impairment, the domain of a project that "
    "re-implements a recent cross-modal obstacle-avoidance wearable (WOAD) and extends it into a phone-based, offline, "
    "spoken guidance prototype (NeuroSonic). We substantiate the problem with WHO, Global Burden of Disease and Indian "
    "national survey statistics: at least 2.2 billion people have a vision impairment, 43.3 million were blind in 2020 "
    "and 61 million are projected by 2050, and 1.99&nbsp;% of Indians aged 50 and over are blind. We compare published "
    "systems (wearable RGB-D and ToF devices, robot guides, segmentation methods), nine verified patents from 1981 to "
    "2022, and eight commercial products from smart canes to free smartphone apps and robotic guides. The comparison "
    "shows that strong research results depend on custom hardware, that affordable products work on demand rather than "
    "continuously, and that continuous, motion-aware warnings from an ordinary phone are not described in the sampled "
    "literature, patents or products. We close with five technology trends (recognition, detection transformers, "
    "depth fusion, local offloading, and vision-language models with offline speech) and their adaptation status, "
    "which define the proposed work.")

ABS_DA2 = abstract(
    "We re-implement and evaluate the base paper of this project, WOAD (Gao et al., Nature Communications, 2025), a "
    "wearable obstacle-avoidance system whose phone runs a YOLOv5-based detector that fuses near-infrared and "
    "colour-mapped depth images with transformer blocks. The released scripts did not run with current libraries, so we "
    "wrote a standalone inference package whose outputs are bit-identical to the original code (maximum absolute "
    "difference 0.0) and showed by ablation that both modalities are used, with near-infrared dominant. A dataset audit "
    "found that the published data is not the data behind the reported detector accuracy (mAP@0.5 0.669): its classes "
    "differ and none of the run's 187 validation frames is in it. With the original metric code, the released "
    "checkpoint reaches a cross-dataset person AP@0.5 of 0.218 (validation, 129 people) and 0.173 (training split, 458 "
    "people), missing most cyclists and distant people, and it loses about 73&nbsp;% of detections on darker sensor "
    "recordings. We derive eight gaps, among them the dependence on a specific sensor, unreproducible accuracy, the "
    "lack of motion semantics, distance and navigation, and propose a phone-camera system with a recall-selected "
    "detector, camera-motion-compensated tracking, offline speech and routing on a laptop GPU.",
    KW.replace("RF-DETR; ", "reproducibility; cross-modal learning; "))

ABS_DA3 = abstract(
    "We implement and evaluate NeuroSonic, a research prototype in which an iPhone browser acts as the camera, "
    "microphone, GPS receiver and speaker of a perception and navigation system running on a laptop over local Wi-Fi, "
    "without internet. Four real-time detectors were benchmarked on the same 365 near-infrared images with 129 people; "
    "RF-DETR Nano gave the highest person AP@0.5 (0.660) and recall at the operating threshold (0.729) at 21.3&nbsp;ms "
    "on an RTX&nbsp;4050 Laptop GPU, with SSDLite as CPU fall-back. Detections are tracked with a ByteTrack-style "
    "association that compensates for camera motion estimated with Lucas&ndash;Kanade flow and RANSAC, and two "
    "conservative events, entering the walking path and crossing in front, are spoken with an offline neural voice. "
    "Offline voice commands and OpenStreetMap A* routing complete the system. In loopback browser tests the pipeline "
    "sustained about 5 frames/s with a median capture-to-answer time of 67&nbsp;ms. Three serving problems were found "
    "and fixed: idle CPU threads (712&nbsp;% to 121&nbsp;% of one core), per-request inference threads, and GPU power "
    "states at low frame rates (mitigated with FP16 at unchanged accuracy). Ten-minute soak tests ran without errors. "
    "Field validation with an iPhone and users is pending; the system is not a safety device.")

COMBINED_SUBS = [
    ("(Review&nbsp;2)", "(see the base-paper re-implementation)"),
    ("(Review&nbsp;3)", "(see the implementation and results)"),
    ("Review&nbsp;3 reports the\nimplementation and its results.", "The following sections report the implementation "
                                                                   "and its results."),
    ("(see the IDF in Lab&nbsp;9)", "(an invention disclosure has been prepared alongside this work)"),
    ("this is the subject of the invention disclosure (Lab&nbsp;9)", "this is the subject of a separate invention "
                                                                      "disclosure"),
    ("This first review covers the domain, the size of the problem, and a\ncomparative survey of publications, patents "
     "and products, followed by the technology trends that shape the proposed\nwork.",
     "This work first surveys the domain, the size of the problem, publications, patents, products and technology "
     "trends; it then re-implements the base paper and identifies its gaps; finally it presents the design, "
     "implementation and evaluation of the proposed system."),
    ("The scope of this survey is deliberately bounded.", "The scope of the survey is deliberately bounded."),
]

ABS_FULL = abstract(
    "Pedestrians with visual impairment need to know both what is in front of them now and where to turn. We survey "
    "the problem (at least 2.2 billion people with vision impairment; 43.3 million blind in 2020, 61 million projected "
    "by 2050; 1.99&nbsp;% blindness among Indians aged 50+), and compare published systems, nine patents and eight "
    "products. We then re-implement the base paper, WOAD (Nature Communications, 2025), a near-infrared + depth "
    "cross-modal detector: our standalone version is bit-identical to the original, but its reported accuracy cannot be "
    "reproduced with the published data, its cross-dataset person AP@0.5 is 0.218, and it cannot be driven by a phone "
    "camera. From eight identified gaps we derive NeuroSonic, in which an iPhone browser is the camera, microphone, GPS "
    "and speaker of a system running offline on a laptop GPU. RF-DETR Nano, selected among four detectors for its "
    "person AP@0.5 (0.660) and recall (0.729), feeds a camera-motion-compensated tracker that announces people or "
    "vehicles entering or crossing the walking path without reacting to the user's own movement. Offline neural speech, "
    "voice commands and OpenStreetMap routing complete the system. On the laptop it sustained about 5 frames/s with a "
    "median capture-to-answer time of 67&nbsp;ms; three serving problems were found and fixed, and ten-minute soak tests "
    "ran without errors. Field validation with an iPhone and users is pending; the system is not a safety device.")

TITLE_FULL = ("NeuroSonic: From a Cross-Modal Wearable Obstacle Detector to an Offline, Phone-Based Spoken "
              "Walking-Path Awareness and Navigation Prototype for Visually Impaired Pedestrians")

SEC_FULL = ["d1_intro", "d1_stats", "d1_pubs", "d1_patents", "d1_products", "d1_trends", "d2_base", "d2_reimpl", "d2_extra",
            "d2_gaps", "d2_proposed", "d3_arch", "d3_methods", "d3_results", "d3_discussion"]

DOCS = {
    "DA1": dict(
        file="01_DA1_Review1_Survey_and_Comparative_Analysis.pdf", style="ieee", min_pages=7,
        short="Review 1 Survey",
        title="Assistive Navigation and Obstacle Awareness for Visually Impaired Pedestrians: A Survey of Publications, "
              "Patents and Products, and Technology Trends",
        authors=AUTHORS + '<div class="note-top">Review 1 (DA1): domain introduction, problem statistics, comparative '
                          'surveys of publications, IPRs and products, and technology trends.</div>',
        abstract=ABS_DA1,
        sections=["d1_intro", "d1_stats", "d1_pubs", "d1_patents", "d1_products", "d1_trends", "d1_conclusion"]),
    "DA2": dict(
        file="02_DA2_Review2_Base_Paper_Reimplementation_Gaps_and_Proposed_Work.pdf", style="ieee", min_pages=7,
        short="Review 2 Base Paper",
        title="Re-implementing a Cross-Modal Wearable Obstacle Detector: Reproducibility, Gaps and a Proposed "
              "Phone-Based Alternative",
        authors=AUTHORS + '<div class="note-top">Review 2 (DA2): base-paper re-implementation, cons and gap '
                          'identification, and proposed work.</div>',
        abstract=ABS_DA2,
        sections=["d2_intro", "d2_base", "d2_reimpl", "d2_extra", "d2_gaps", "d2_proposed", "d2_conclusion"]),
    "DA3": dict(
        file="03_DA3_Review3_Implementation_Architecture_and_Results.pdf", style="ieee", min_pages=7,
        short="Review 3 Implementation",
        title="NeuroSonic: Implementation and Evaluation of a Laptop-Assisted, Offline Smartphone Prototype for Spoken "
              "Walking-Path Awareness and Navigation",
        authors=AUTHORS + '<div class="note-top">Review 3 (DA3): implementation, architecture and methodology, and '
                          'result analysis of the proposed work.</div>',
        abstract=ABS_DA3,
        sections=["d3_intro", "d3_arch", "fig_proparch", "d3_methods", "d3_results", "d3_discussion"]),
    "Lab10": dict(
        file="06_Lab10_IEEE_Two_Column_Paper_Draft.pdf", style="ieee", min_pages=14,
        short="Lab 10 IEEE Draft", title=TITLE_FULL,
        authors=AUTHORS + '<div class="note-top">Lab 10: IEEE two-column manuscript draft (survey, base-paper '
                          're-implementation, proposed work, implementation and results).</div>',
        abstract=ABS_FULL, sections=SEC_FULL, subs=COMBINED_SUBS),
}


def form_front(title, meta):
    return f'<div class="doc-title"><h1>{title}</h1><div class="meta">{meta}</div></div>'


META = "NeuroSonic project &middot; Allwin Raj &middot; Vellore Institute of Technology &middot; 3 November 2026"

REPORT_SECTIONS = ["d1_intro", "d1_stats", "d1_pubs", "d1_patents", "d1_products", "d1_trends", "d1_conclusion",
                   "d2_base", "d2_reimpl", "d2_extra", "d2_gaps", "d2_proposed", "d3_arch", "d3_methods",
                   "d3_results", "d3_discussion", "demo", "r_appx"]

DOCS.update({
    "Report": dict(file="05_Final_Consolidated_Project_Report.pdf", style="report", min_pages=20,
                   short="NeuroSonic Final Report", front=open(__import__("pathlib").Path(__file__).parent /
                                                               "sections" / "r_front.html", encoding="utf-8").read(),
                   toc=True, sections=REPORT_SECTIONS, subs=COMBINED_SUBS),
    "Lab9": dict(file="09_Lab9_IPR_IDF_B_Draft.pdf", style="form", short="Lab 9 IDF B Draft",
                 front=form_front("Invention Disclosure Form (IDF) &ndash; Part B: Technical Disclosure (Draft)", META),
                 sections=["lab9_idf"]),
    "Demo": dict(file="04_Project_Demo_Existing_vs_Proposed.pdf", style="form", short="Project Demo",
                 front=form_front("Project Demo: Existing Implementation and Proposed Work (Differentiation)", META),
                 sections=["demo"]),
    "Links": dict(file="07_GitHub_Dataset_and_Video_Links.pdf", style="form", short="GitHub and Video Links",
                  front=form_front("GitHub Repository, Dataset and Demonstration Video", META),
                  sections=["links"]),
    "Venues": dict(file="08_Publication_Venue_Identification.pdf", style="form", short="Publication Venues",
                   front=form_front("Identification of Scopus-Indexed Venues (Q1&ndash;Q4), Book Chapter and IPR", META),
                   sections=["venues"]),
    "Checklist": dict(file="00_Submission_Checklist.pdf", style="form", short="Submission Checklist",
                      front=form_front("Submission Checklist", META), sections=["checklist"]),
})
