"""Generate a native Linux SMB proof-of-concept from ROM-derived assets.

The generated app is intentionally not an emulator wrapper. The ROM is used at
generation time only to render SMB level/player assets through qlnes' existing
reverse-engineered exporters. The runtime is a small C/SDL2 program that loads
raw RGB/RGBA assets and implements a minimal native side-scroller loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .det import sha256_file
from .smb_graphics import render_smb_characters, render_smb_level, validate_smb_nrom


@dataclass(frozen=True)
class SmbNativeExport:
    rom: Path
    out_dir: Path
    app_name: str
    stage: str
    executable_name: str
    source: Path
    build_script: Path
    appimage_script: Path
    manifest_json: Path
    files: list[Path] = field(default_factory=list)


def slugify_binary_name(name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.strip())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "smb-native"


def create_smb_native_port(
    rom_path: Path | str,
    out_dir: Path | str,
    *,
    app_name: str = "Super Mario Bros Native",
    stage: str = "1-1",
    force: bool = False,
) -> SmbNativeExport:
    """Generate a C/SDL2 native SMB MVP project and AppImage build scripts."""
    rom = Path(rom_path)
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(f"{out} is not empty (use force=True)")
    out.mkdir(parents=True, exist_ok=True)

    rom_bytes = rom.read_bytes()
    validate_smb_nrom(rom_bytes)

    app_slug = slugify_binary_name(app_name)
    src_dir = out / "src"
    assets_dir = out / "assets"
    build_dir = out / "_asset-build"
    src_dir.mkdir(exist_ok=True)
    assets_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    level = render_smb_level(rom, build_dir / "levels", stage=stage, max_columns=256)
    characters = render_smb_characters(rom, build_dir / "characters")
    mario_png = build_dir / "characters" / "players" / "small-stand.png"
    if not mario_png.exists():
        raise RuntimeError(f"expected SMB player sprite missing: {mario_png}")

    level_raw = assets_dir / "level_1_1.rgb"
    mario_raw = assets_dir / "mario_small_stand.rgba"
    _write_rgb(level.png, level_raw)
    mario_size = _write_rgba(mario_png, mario_raw)

    main_c = src_dir / "main.c"
    main_c.write_text(
        _main_c_source(
            app_name=app_name,
            level_width=level.width,
            level_height=level.height,
            mario_width=mario_size[0],
            mario_height=mario_size[1],
        ),
        encoding="utf-8",
    )
    build_sh = out / "build.sh"
    build_sh.write_text(_build_sh(app_slug), encoding="utf-8")
    build_sh.chmod(0o755)

    appimage_sh = out / "build-appimage.sh"
    appimage_sh.write_text(_appimage_sh(app_slug, app_name), encoding="utf-8")
    appimage_sh.chmod(0o755)

    desktop = out / f"{app_slug}.desktop"
    desktop.write_text(
        f"""[Desktop Entry]
Type=Application
Name={app_name}
Exec={app_slug}
Icon={app_slug}
Categories=Game;
Terminal=false
""",
        encoding="utf-8",
    )

    icon = out / f"{app_slug}.svg"
    icon.write_text(_icon_svg(), encoding="utf-8")

    manifest = out / "smb-native-manifest.json"
    files = [
        main_c,
        build_sh,
        appimage_sh,
        desktop,
        icon,
        level_raw,
        mario_raw,
        manifest,
    ]
    manifest.write_text(
        json.dumps(
            {
                "kind": "smb_native_port_mvp",
                "app_name": app_name,
                "executable_name": app_slug,
                "stage": stage,
                "rom_source": str(rom),
                "rom_sha256": sha256_file(rom),
                "runtime": "C/SDL2 native side-scroller MVP; no ROM or emulator is bundled",
                "level": {
                    "source_png": str(level.png),
                    "asset": str(level_raw.relative_to(out)),
                    "width": level.width,
                    "height": level.height,
                    "columns": level.columns,
                    "rows": level.rows,
                },
                "player": {
                    "source_png": str(mario_png),
                    "asset": str(mario_raw.relative_to(out)),
                    "width": mario_size[0],
                    "height": mario_size[1],
                },
                "character_manifest": str(characters.manifest_json),
                "build": {
                    "elf": f"dist/{app_slug}",
                    "appimage": f"{app_slug}.AppImage",
                },
                "notes": [
                    "The generated runtime does not read a .nes file.",
                    "This is a native MVP, not a complete SMB engine yet.",
                    "Controls: arrows or A/D to move, Space/W/Up to jump, Esc to quit.",
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return SmbNativeExport(
        rom=rom,
        out_dir=out,
        app_name=app_name,
        stage=stage,
        executable_name=app_slug,
        source=main_c,
        build_script=build_sh,
        appimage_script=appimage_sh,
        manifest_json=manifest,
        files=files,
    )


def _write_rgb(source_png: Path, target: Path) -> tuple[int, int]:
    image = Image.open(source_png).convert("RGB")
    target.write_bytes(image.tobytes())
    return image.size


def _write_rgba(source_png: Path, target: Path) -> tuple[int, int]:
    image = Image.open(source_png).convert("RGBA")
    target.write_bytes(image.tobytes())
    return image.size


def _main_c_source(
    *, app_name: str, level_width: int, level_height: int, mario_width: int, mario_height: int
) -> str:
    return f"""#include <SDL2/SDL.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define APP_TITLE "{app_name}"
#define SCREEN_W 256
#define SCREEN_H 240
#define SCALE 3
#define LEVEL_W {level_width}
#define LEVEL_H {level_height}
#define MARIO_W {mario_width}
#define MARIO_H {mario_height}

static uint8_t *read_asset(const char *path, size_t expected) {{
    FILE *f = fopen(path, "rb");
    if (!f) {{
        fprintf(stderr, "missing asset: %s\\n", path);
        return NULL;
    }}
    uint8_t *data = (uint8_t *)malloc(expected);
    if (!data) {{
        fclose(f);
        return NULL;
    }}
    size_t n = fread(data, 1, expected, f);
    fclose(f);
    if (n != expected) {{
        fprintf(stderr, "bad asset size for %s: got %zu expected %zu\\n", path, n, expected);
        free(data);
        return NULL;
    }}
    return data;
}}

static void draw_level(uint32_t *frame, const uint8_t *level, int camera_x) {{
    for (int y = 0; y < SCREEN_H; y++) {{
        int sy = y < LEVEL_H ? y : LEVEL_H - 1;
        for (int x = 0; x < SCREEN_W; x++) {{
            int sx = camera_x + x;
            if (sx < 0) sx = 0;
            if (sx >= LEVEL_W) sx = LEVEL_W - 1;
            size_t i = ((size_t)sy * LEVEL_W + sx) * 3;
            frame[(size_t)y * SCREEN_W + x] = 0xFF000000u | ((uint32_t)level[i] << 16) |
                ((uint32_t)level[i + 1] << 8) | (uint32_t)level[i + 2];
        }}
    }}
}}

static void draw_mario(uint32_t *frame, const uint8_t *mario, int x, int y, bool flip) {{
    for (int py = 0; py < MARIO_H; py++) {{
        int dy = y + py;
        if (dy < 0 || dy >= SCREEN_H) continue;
        for (int px = 0; px < MARIO_W; px++) {{
            int sx = flip ? (MARIO_W - 1 - px) : px;
            int dx = x + px;
            if (dx < 0 || dx >= SCREEN_W) continue;
            size_t si = ((size_t)py * MARIO_W + sx) * 4;
            uint8_t a = mario[si + 3];
            if (a < 16) continue;
            frame[(size_t)dy * SCREEN_W + dx] = 0xFF000000u |
                ((uint32_t)mario[si] << 16) | ((uint32_t)mario[si + 1] << 8) | mario[si + 2];
        }}
    }}
}}

int main(int argc, char **argv) {{
    const char *base = SDL_GetBasePath();
    char level_path[4096];
    char mario_path[4096];
    snprintf(level_path, sizeof(level_path), "%sassets/level_1_1.rgb", base ? base : "");
    snprintf(mario_path, sizeof(mario_path), "%sassets/mario_small_stand.rgba", base ? base : "");

    uint8_t *level = read_asset(level_path, (size_t)LEVEL_W * LEVEL_H * 3);
    uint8_t *mario = read_asset(mario_path, (size_t)MARIO_W * MARIO_H * 4);
    if (!level || !mario) return 2;

    if (argc > 1 && SDL_strcmp(argv[1], "--self-test") == 0) {{
        free(level);
        free(mario);
        return 0;
    }}

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER) != 0) {{
        fprintf(stderr, "SDL_Init failed: %s\\n", SDL_GetError());
        return 3;
    }}
    SDL_Window *window = SDL_CreateWindow(APP_TITLE, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        SCREEN_W * SCALE, SCREEN_H * SCALE, SDL_WINDOW_SHOWN);
    SDL_Renderer *renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    SDL_Texture *texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888,
        SDL_TEXTUREACCESS_STREAMING, SCREEN_W, SCREEN_H);
    uint32_t *frame = (uint32_t *)malloc((size_t)SCREEN_W * SCREEN_H * sizeof(uint32_t));
    if (!window || !renderer || !texture || !frame) {{
        fprintf(stderr, "SDL setup failed: %s\\n", SDL_GetError());
        return 4;
    }}

    float mario_x = 48.0f;
    float mario_y = 176.0f;
    float vx = 0.0f;
    float vy = 0.0f;
    bool running = true;
    bool facing_left = false;
    const float ground_y = 176.0f;
    uint32_t last = SDL_GetTicks();

    while (running) {{
        SDL_Event e;
        while (SDL_PollEvent(&e)) {{
            if (e.type == SDL_QUIT) running = false;
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) running = false;
        }}
        const uint8_t *keys = SDL_GetKeyboardState(NULL);
        float move = 0.0f;
        if (keys[SDL_SCANCODE_LEFT] || keys[SDL_SCANCODE_A]) move -= 1.0f;
        if (keys[SDL_SCANCODE_RIGHT] || keys[SDL_SCANCODE_D]) move += 1.0f;
        if (move < 0) facing_left = true;
        if (move > 0) facing_left = false;
        vx = move * 100.0f;
        bool jump = keys[SDL_SCANCODE_SPACE] || keys[SDL_SCANCODE_UP] || keys[SDL_SCANCODE_W];
        if (jump && mario_y >= ground_y - 0.5f) vy = -245.0f;

        uint32_t now = SDL_GetTicks();
        float dt = (float)(now - last) / 1000.0f;
        if (dt > 0.05f) dt = 0.05f;
        last = now;

        vy += 620.0f * dt;
        mario_x += vx * dt;
        mario_y += vy * dt;
        if (mario_y > ground_y) {{
            mario_y = ground_y;
            vy = 0.0f;
        }}
        if (mario_x < 0.0f) mario_x = 0.0f;
        if (mario_x > LEVEL_W - MARIO_W) mario_x = LEVEL_W - MARIO_W;

        int camera = (int)mario_x - 96;
        if (camera < 0) camera = 0;
        if (camera > LEVEL_W - SCREEN_W) camera = LEVEL_W - SCREEN_W;
        draw_level(frame, level, camera);
        draw_mario(frame, mario, (int)mario_x - camera, (int)mario_y, facing_left);

        SDL_UpdateTexture(texture, NULL, frame, SCREEN_W * (int)sizeof(uint32_t));
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, NULL, NULL);
        SDL_RenderPresent(renderer);
    }}

    free(frame);
    free(level);
    free(mario);
    SDL_DestroyTexture(texture);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}}
"""


def _build_sh(app_slug: str) -> str:
    return f"""#!/usr/bin/env sh
set -eu
command -v pkg-config >/dev/null 2>&1 || {{ echo "pkg-config is required" >&2; exit 1; }}
pkg-config --exists sdl2 || {{ echo "SDL2 development files are required (pkg-config sdl2)" >&2; exit 1; }}
mkdir -p dist
cc -O2 -Wall -Wextra src/main.c -o "dist/{app_slug}" $(pkg-config --cflags --libs sdl2)
mkdir -p dist/assets
cp assets/*.rgb assets/*.rgba dist/assets/
"""


def _appimage_sh(app_slug: str, app_name: str) -> str:
    return f"""#!/usr/bin/env sh
set -eu
./build.sh
APPIMAGETOOL="${{APPIMAGETOOL:-}}"
if [ -z "$APPIMAGETOOL" ]; then
  if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL=appimagetool
  else
    mkdir -p .tools
    ARCH="$(uname -m)"
    case "$ARCH" in
      x86_64|amd64) APPIMAGE_ARCH=x86_64 ;;
      aarch64|arm64) APPIMAGE_ARCH=aarch64 ;;
      *) echo "unsupported AppImage architecture: $ARCH" >&2; exit 1 ;;
    esac
    APPIMAGETOOL=".tools/appimagetool-$APPIMAGE_ARCH.AppImage"
    if [ ! -x "$APPIMAGETOOL" ]; then
      URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$APPIMAGE_ARCH.AppImage"
      if command -v curl >/dev/null 2>&1; then
        curl -L "$URL" -o "$APPIMAGETOOL"
      elif command -v wget >/dev/null 2>&1; then
        wget -O "$APPIMAGETOOL" "$URL"
      else
        echo "curl or wget is required to download appimagetool" >&2
        exit 1
      fi
      chmod +x "$APPIMAGETOOL"
    fi
  fi
fi
rm -rf AppDir
mkdir -p AppDir/usr/bin AppDir/usr/lib AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/scalable/apps
cp "dist/{app_slug}" AppDir/usr/bin/
cp -R dist/assets AppDir/usr/bin/assets
cp "{app_slug}.desktop" "AppDir/usr/share/applications/{app_slug}.desktop"
cp "{app_slug}.svg" "AppDir/usr/share/icons/hicolor/scalable/apps/{app_slug}.svg"
SDL_LIB="$(ldd "dist/{app_slug}" | awk '/libSDL2-2.0.so.0/ {{print $3; exit}}')"
if [ -n "$SDL_LIB" ] && [ -f "$SDL_LIB" ]; then
  cp "$SDL_LIB" AppDir/usr/lib/
fi
cat > AppDir/AppRun <<'EOF'
#!/usr/bin/env sh
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$HERE/usr/lib:${{LD_LIBRARY_PATH:-}}"
exec "$HERE/usr/bin/{app_slug}" "$@"
EOF
chmod +x AppDir/AppRun
cp "{app_slug}.desktop" "AppDir/{app_slug}.desktop"
cp "{app_slug}.svg" "AppDir/{app_slug}.svg"
"$APPIMAGETOOL" AppDir "{app_slug}.AppImage"
"""


def _icon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<rect width="256" height="256" rx="32" fill="#5c94fc"/>
<rect x="0" y="184" width="256" height="72" fill="#c84c0c"/>
<rect x="56" y="96" width="64" height="80" fill="#d82800"/>
<rect x="80" y="64" width="48" height="32" fill="#f8d878"/>
<rect x="120" y="128" width="32" height="48" fill="#0058f8"/>
<rect x="48" y="176" width="136" height="16" fill="#00a800"/>
</svg>
"""
