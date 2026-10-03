These compact PNGs are derived from `ezyschool-ui/public/img/logo-light-full.png`
and `logo-dark-full.png` at 800 pixels wide. The backend embeds both in HTML
emails as Content-ID attachments, so recipients do not fetch logos from R2 or
the frontend. The default (light) variant remains visible in clients that do
not support email dark-mode CSS.

When the source logos change, regenerate both files from the workspace root:

```sh
magick ezyschool-ui/public/img/logo-light-full.png -resize 800x -strip -define png:compression-level=9 backend-2/common/assets/email/logo-light.png
magick ezyschool-ui/public/img/logo-dark-full.png -resize 800x -strip -define png:compression-level=9 backend-2/common/assets/email/logo-dark.png
```
