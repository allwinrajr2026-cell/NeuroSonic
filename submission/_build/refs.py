"""Reference database (IEEE style). Every entry was checked on 2026-11-03 (web search / publisher, patent office
or repository pages) or was already verified for the NeuroSonic manuscript. Cite in fragments as [[key]] or
[[key1,key2]]; build.py numbers them in order of first citation per document."""

REFS = {
    # --- statistics -------------------------------------------------------------------------------------------
    "who": 'World Health Organization, "Blindness and vision impairment," Fact sheet, 10 Feb. 2026. [Online]. '
           'Available: https://www.who.int/news-room/fact-sheets/detail/blindness-and-visual-impairment',
    "whoreport": 'World Health Organization, <i>World Report on Vision</i>. Geneva, Switzerland: WHO, Oct. 2019. '
                 '[Online]. Available: https://www.who.int/news/item/08-10-2019-who-launches-first-world-report-on-vision',
    "gbd": 'GBD 2019 Blindness and Vision Impairment Collaborators and Vision Loss Expert Group of the Global Burden of '
           'Disease Study, "Trends in prevalence of blindness and distance and near vision impairment over 30 years: an '
           'analysis for the Global Burden of Disease Study," <i>Lancet Global Health</i>, vol. 9, no. 2, pp. e130&ndash;e143, '
           '2021, doi: 10.1016/S2214-109X(20)30425-3.',
    "nbvis": 'National Programme for Control of Blindness and Visual Impairment, Ministry of Health and Family Welfare, '
             'Govt. of India, and Dr. R. P. Centre for Ophthalmic Sciences, AIIMS, "National Blindness and Visual '
             'Impairment Survey 2015&ndash;2019," India Vision Atlas. [Online]. Available: https://indiavisionatlasnpcb.aiims.edu/',
    "nbvis2": 'Vikaspedia (Govt. of India), "National Blindness and Visual Impairment Survey," summary of the 2015&ndash;2019 '
              'survey. [Online]. Available: https://vikaspedia.in/health/health-directory/national-blindness-and-visual-impairment-survey',
    # --- base paper and publications -------------------------------------------------------------------------
    "woad": 'Y. Gao, D. Wu, J. Song, X. Zhang, B. Hou, H. Liu, J. Liao, and L. Zhou, "A wearable obstacle avoidance '
            'device for visually impaired individuals with cross-modal learning," <i>Nature Communications</i>, vol. 16, '
            'Art. no. 2857, Mar. 2025, doi: 10.1038/s41467-025-58085-x.',
    "real2019": 'S. Real and A. Araujo, "Navigation systems for the blind and visually impaired: past work, challenges, '
                'and open problems," <i>Sensors</i>, vol. 19, no. 15, Art. no. 3404, 2019, doi: 10.3390/s19153404.',
    "kuriakose2020": 'B. Kuriakose, R. Shrestha, and F. E. Sandnes, "Tools and technologies for blind and visually '
                     'impaired navigation support: a review," <i>IETE Technical Review</i>, 2020, '
                     'doi: 10.1080/02564602.2020.1819893.',
    "bai2019": 'J. Bai, Z. Liu, Y. Lin, Y. Li, S. Lian, and D. Liu, "Wearable travel aid for environment perception and '
               'navigation of visually impaired people," <i>Electronics</i>, 2019 (arXiv:1904.13037).',
    "lin2019": 'Y. Lin, K. Wang, W. Yi, and S. Lian, "Deep learning based wearable assistive system for visually '
               'impaired people," in <i>Proc. ICCV Workshop on Assistive Computer Vision and Robotics (ACVR)</i>, 2019 '
               '(arXiv:1908.03364).',
    "xu2023": 'P. Xu, A. Song, and K. Wang, "Intelligent head-mounted obstacle avoidance wearable for the blind and '
              'visually impaired," <i>Sensors</i>, vol. 23, no. 23, Art. no. 9598, Dec. 2023, doi: 10.3390/s23239598.',
    "tang2025": 'Tang <i>et al.</i>, "Human-centred design and fabrication of a wearable multimodal visual assistance '
                'system," <i>Nature Machine Intelligence</i>, vol. 7, pp. 627&ndash;638, Apr. 2025, '
                'doi: 10.1038/s42256-025-01018-6.',
    "cabot": 'J. Guerreiro, D. Sato, S. Asakawa, H. Dong, K. M. Kitani, and C. Asakawa, "CaBot: designing and evaluating '
             'an autonomous navigation robot for blind people," in <i>Proc. 21st Int. ACM SIGACCESS Conf. Computers and '
             'Accessibility (ASSETS)</i>, 2019, pp. 68&ndash;82, doi: 10.1145/3308561.3353771.',
    "ghahr2025": 'T. Ghahremanians and H. Mahvash Mohammadi, "Independent pathfinding with collision avoidance for '
                 'visually impaired individuals," <i>Scientific Reports</i>, vol. 15, Art. no. 35441, Oct. 2025, '
                 'doi: 10.1038/s41598-025-19387-8.',
    "yan2025": 'F. Yan, T. Zeng, and M. He, "Implementing blind navigation through multi-modal sensing and gait '
               'guidance," arXiv:2506.19593, Jun. 2025.',
    "aviper": 'X. Li <i>et al.</i>, "AviPer: assisting visually impaired people to perceive the world with visual-tactile '
              'multimodal attention network," <i>CCF Trans. Pervasive Computing and Interaction</i>, 2022.',
    # --- patents -----------------------------------------------------------------------------------------------
    "pat_polaroid": 'G. M. Elchinger (Polaroid Corp.), "Mobility cane for the blind incorporating ultrasonic obstacle '
                    'sensing apparatus," U.S. Patent 4 280 204, Jul. 21, 1981.',
    "pat_caltech": 'W. Fink and M. Humayun, "Digital object recognition audio-assistant for the visually impaired," '
                   'U.S. Patent Appl. Publ. 2005/0208457 A1, Sep. 22, 2005 (abandoned).',
    "pat_searle": 'C. Searle, S. Searle, and J. Holbrook, "Navigation device for the visually-impaired," U.S. Patent '
                  '9 429 446 B1, Aug. 30, 2016.',
    "pat_st": 'F. D\'Angelo and S. Corona (STMicroelectronics S.r.l.), "Wearable obstacle-detection device, and '
              'corresponding method and computer program product," U.S. Patent 9 846 231 B2, Dec. 19, 2017.',
    "pat_toyota": 'T. Chen and R. F. Tow (Toyota Motor Engineering and Manufacturing North America), "Vision-assist '
                  'systems and methods for assisting visually impaired users with navigating an environment using '
                  'simultaneous audio outputs," U.S. Patent 9 993 384 B1, Jun. 12, 2018.',
    "pat_frankel": 'D. M. Frankel, "Systems and methods for blind and visually impaired person environment navigation '
                   'assistance," U.S. Patent 10 299 982 B2, May 28, 2019.',
    "pat_ford": 'D. Bell, S. Houts, L. V. Keiser, J. Oh, and G. Pandey (Ford Global Technologies), "Navigational aid for '
                'the visually impaired," U.S. Patent 10 809 079 B2, Oct. 20, 2020.',
    "pat_brown": 'B. Kimia (Brown University), "Navigation methods and apparatus for the visually impaired," U.S. Patent '
                 '11 112 261 B2, Sep. 7, 2021.',
    "pat_aph": 'D. K. Creasy, J. Karr, M. Klarer, R. Meredith, L. Skutchan, and J. Wegner (American Printing House for '
               'the Blind), "Navigation assistance for the visually impaired," U.S. Patent 11 318 050 B2, May 3, 2022.',
    # --- products ----------------------------------------------------------------------------------------------
    "p_aarp": 'AARP, "Low vision technology" (product overview incl. OrCam MyEye Pro and WeWALK prices). [Online]. '
              'Available: https://www.aarp.org/health/conditions-treatments/low-vision-technology/',
    "p_rnib": 'RNIB Shop, "OrCam MyEye Pro" and "OrCam MyEye Smart" product pages. [Online]. Available: '
              'https://shop.rnib.org.uk/products/orcam-myeye-pro',
    "p_wewalk": 'IAPB Valued Supplier directory, "WeWALK." [Online]. Available: https://valuedsupplier.iapb.org/suppliers/wewalk',
    "p_perkins": 'Perkins School for the Blind, "Visual assistance apps post roundup." [Online]. Available: '
                 'https://www.perkins.org/resource/visual-assistance-apps-post-roundup/',
    "p_lookout": 'Thomas Pocklington Trust, "Google Lookout review." [Online]. Available: '
                 'https://www.pocklington-trust.org.uk/technology/tech-news-and-views/google-lookout-review/',
    "p_noa": 'Ophthalmology Times, "Smart harness alerts visually impaired people to obstacles in their paths"; and '
             'RealSense, "Biped.ai: real-time guidance for the visually impaired" (case study). [Online]. Available: '
             'https://www.ophthalmologytimes.com/view/smart-harness-alerts-visually-impaired-people-to-obstacles-in-their-paths',
    "p_glide": 'Popular Science, "Can this robot help solve a guide dog shortage?"; ITU AI for Good, "Meet Glidance." '
               '[Online]. Available: https://popsci.com/technology/can-this-robot-help-solve-a-guide-dog-shortage',
    "p_smartcane": 'Wellcome Trust grant 092882/A/10/Z (SmartCane, IIT Delhi Assistech with Saksham Trust); device '
                   'description in ThisAbility, "SmartCane." [Online]. Available: '
                   'https://grantnav.threesixtygiving.org/grant/360G-Wellcome-092882_A_10_Z',
    # --- methods and software ----------------------------------------------------------------------------------
    "yolo": 'J. Redmon, S. Divvala, R. Girshick, and A. Farhadi, "You only look once: unified, real-time object '
            'detection," in <i>Proc. IEEE CVPR</i>, 2016.',
    "yolov5": 'G. Jocher <i>et al.</i>, "Ultralytics YOLOv5," software, 2020. [Online]. Available: https://github.com/ultralytics/yolov5',
    "ssd": 'W. Liu <i>et al.</i>, "SSD: single shot multibox detector," in <i>Proc. ECCV</i>, 2016.',
    "mbv3": 'A. Howard <i>et al.</i>, "Searching for MobileNetV3," in <i>Proc. IEEE ICCV</i>, 2019.',
    "transformer": 'A. Vaswani <i>et al.</i>, "Attention is all you need," in <i>Proc. NeurIPS</i>, 2017.',
    "detr": 'N. Carion <i>et al.</i>, "End-to-end object detection with transformers," in <i>Proc. ECCV</i>, 2020.',
    "rfdetr": 'Roboflow, "RF-DETR: real-time detection transformer," software, Apache-2.0. [Online]. Available: '
              'https://github.com/roboflow/rf-detr',
    "dinov2": 'M. Oquab <i>et al.</i>, "DINOv2: learning robust visual features without supervision," <i>Trans. Machine '
              'Learning Research</i>, 2024 (arXiv:2304.07193).',
    "yolo26": 'Ultralytics, "YOLO26 documentation," software, AGPL-3.0. [Online]. Available: https://docs.ultralytics.com/',
    "coco": 'T.-Y. Lin <i>et al.</i>, "Microsoft COCO: common objects in context," in <i>Proc. ECCV</i>, 2014.',
    "sort": 'A. Bewley, Z. Ge, L. Ott, F. Ramos, and B. Upcroft, "Simple online and realtime tracking," in <i>Proc. IEEE '
            'ICIP</i>, 2016.',
    "bytetrack": 'Y. Zhang <i>et al.</i>, "ByteTrack: multi-object tracking by associating every detection box," in '
                 '<i>Proc. ECCV</i>, 2022.',
    "shitomasi": 'J. Shi and C. Tomasi, "Good features to track," in <i>Proc. IEEE CVPR</i>, 1994.',
    "lk": 'B. D. Lucas and T. Kanade, "An iterative image registration technique with an application to stereo vision," '
          'in <i>Proc. IJCAI</i>, 1981.',
    "bouguet": 'J.-Y. Bouguet, "Pyramidal implementation of the Lucas Kanade feature tracker," Intel Corp., '
               'Microprocessor Research Labs, Tech. Rep., 2000.',
    "ransac": 'M. A. Fischler and R. C. Bolles, "Random sample consensus: a paradigm for model fitting with applications '
              'to image analysis and automated cartography," <i>Commun. ACM</i>, vol. 24, no. 6, pp. 381&ndash;395, 1981.',
    "opencv": 'OpenCV library. [Online]. Available: https://opencv.org/',
    "kaldi": 'D. Povey <i>et al.</i>, "The Kaldi speech recognition toolkit," in <i>Proc. IEEE ASRU Workshop</i>, 2011; '
             'Vosk offline speech recognition. [Online]. Available: https://alphacephei.com/vosk/',
    "piper": 'Piper text-to-speech, software. [Online]. Available: https://github.com/rhasspy/piper',
    "vits": 'J. Kim, J. Kong, and J. Son, "Conditional variational autoencoder with adversarial learning for end-to-end '
            'text-to-speech," in <i>Proc. ICML</i>, 2021.',
    "astar": 'P. E. Hart, N. J. Nilsson, and B. Raphael, "A formal basis for the heuristic determination of minimum cost '
             'paths," <i>IEEE Trans. Systems Science and Cybernetics</i>, vol. 4, no. 2, pp. 100&ndash;107, 1968.',
    "osm": 'OpenStreetMap contributors, OpenStreetMap (ODbL 1.0). [Online]. Available: https://www.openstreetmap.org',
    "dsac": 'P. Christodoulou, "Soft actor-critic for discrete action settings," arXiv:1910.07207, 2019.',
    "gemini": 'Google, "Gemini API documentation." [Online]. Available: https://ai.google.dev/',
    # --- venues ------------------------------------------------------------------------------------------------
    "sjr_lnns": 'SCImago, "Lecture Notes in Networks and Systems," SJR journal page. [Online]. Available: '
                'https://www.scimagojr.com/journalsearch.php?q=21100901469&amp;tip=sid',
    "sjr_ieeesensors": 'SCImago, "IEEE Sensors Journal," SJR journal page. [Online]. Available: '
                       'https://www.scimagojr.com/journalsearch.php?q=15047&amp;tip=sid',
    "sjr_sensors": 'SCImago, "Sensors," SJR journal page. [Online]. Available: '
                   'https://www.scimagojr.com/journalsearch.php?q=130124&amp;tip=sid',
    "sjr_access": 'SCImago, "IEEE Access," SJR journal page. [Online]. Available: '
                  'https://www.scimagojr.com/journalsearch.php?q=21100374601&amp;tip=sid',
}
