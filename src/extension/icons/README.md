# Extension Icons

This directory must contain the following PNG files before the extension can be loaded in Chrome:

| File           | Size      | Purpose                              |
|----------------|-----------|--------------------------------------|
| `icon16.png`   | 16×16 px  | Favicon / tab strip icon             |
| `icon48.png`   | 48×48 px  | Extensions management page icon      |
| `icon128.png`  | 128×128 px| Chrome Web Store / install dialog    |

## How to create placeholder icons

Any 16×16, 48×48, and 128×128 PNG files will work for local development.
You can generate minimal solid-colour placeholders with ImageMagick:

```bash
magick -size 16x16  xc:"#3B82F6" icons/icon16.png
magick -size 48x48  xc:"#3B82F6" icons/icon48.png
magick -size 128x128 xc:"#3B82F6" icons/icon128.png
```

Or with Python (Pillow):

```python
from PIL import Image

for size in (16, 48, 128):
    img = Image.new("RGBA", (size, size), (59, 130, 246, 255))
    img.save(f"icons/icon{size}.png")
```

## Production icons

Replace the placeholders with branded artwork that follows the
[Chrome Web Store image guidelines](https://developer.chrome.com/docs/webstore/images/)
before publishing.

> **Note:** These PNG files are intentionally excluded from version control
> (`.gitignore`) because binary placeholder blobs add noise to diffs.
> Generate them locally from the commands above.
