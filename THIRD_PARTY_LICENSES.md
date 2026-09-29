# Third party licences

AutoCut redistributes the fonts and icons its window is drawn with, because neither Linux nor macOS ships a suitable grotesque, a monospace with tabular figures or a matching icon set that may be redistributed (ADR 10), and the face detection model that analysis runs (ADR 14). The fonts and icons travel inside the package under `autocut/gui/theme/assets/` and the model under `autocut/core/models/`, each with its licence text beside it.

Python dependencies are not listed here. They are installed from PyPI by pip and keep their own licences in the environment.

## Fonts

| Family        | Version                        | Licence                   | Files                                                 | Upstream                                        |
| ------------- | ------------------------------ | ------------------------- | ----------------------------------------------------- | ----------------------------------------------- |
| Space Grotesk | 2.0 (repository `master`)      | SIL Open Font License 1.1 | `assets/fonts/SpaceGrotesk-{Regular,Medium,Bold}.ttf` | https://github.com/floriankarsten/space-grotesk |
| IBM Plex Mono | 2.5.0 (`@ibm/plex-mono@2.5.0`) | SIL Open Font License 1.1 | `assets/fonts/IBMPlexMono-{Regular,Medium}.ttf`       | https://github.com/IBM/plex                     |

Both are shipped byte for byte as published, with no subsetting and no renaming, which is what keeps the IBM reserved font name condition satisfied. The licence texts are `assets/fonts/SpaceGrotesk-OFL.txt` and `assets/fonts/IBMPlexMono-OFL.txt`.

Space Grotesk publishes no static SemiBold. Weight 600 exists only in its variable font, so the bundle carries Regular, Medium and Bold and the design uses those three.

## Icons

| Set    | Licence | Files                | Upstream                               |
| ------ | ------- | -------------------- | -------------------------------------- |
| Lucide | ISC     | `assets/icons/*.svg` | https://github.com/lucide-icons/lucide |

Twenty icons are bundled, unmodified except that `currentColor` is substituted for a token colour at render time. `assets/icons/LICENSE.txt` is the upstream licence file, which also carries the MIT notice covering the icons Lucide inherited from Feather.

## Models

| Model | Version   | Licence | File                                                    | Upstream                                                                   |
| ----- | --------- | ------- | ------------------------------------------------------- | -------------------------------------------------------------------------- |
| YuNet | `2026may` | MIT     | `autocut/core/models/face_detection_yunet_2026may.onnx` | https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet |

The 224 KB ONNX file is shipped byte for byte as published. Its licence text is `autocut/core/models/YUNET-LICENSE.txt`. It is loaded by OpenCV's `cv2.FaceDetectorYN` and counts faces per frame; it recognises nobody.
