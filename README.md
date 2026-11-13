# Kartlands GP

A 3D arcade kart racer in one HTML file, with models and textures built in Blender. Eight racers, twelve circuits of two to three kilometres, jumps, drifting, twelve items, coins and star tokens, three Grand Prix cups, AI rivals in three classes, two-player split screen, gamepad support, and online rooms over WebRTC.

**Play it:** https://thedickestrick.github.io/kartlands-gp/

## Modes

- **Grand Prix:** four races for one trophy, with points for every place. Three cups, each at Rookie, Pro or Elite. One or two players.
- **Quick race:** any circuit, any rival class, one, three or five laps. One or two players.
- **Online:** host a room or join one with a five-letter code. Up to eight humans, and rivals fill the rest of the grid.

Coins banked, best laps, star tokens found and trophies won are kept in the browser.

## Controls

| Action | Keyboard (solo) | Player 1 (split) | Player 2 (split) | Controller |
|---|---|---|---|---|
| Steer | A / D or arrows | A / D | Left / Right | Either stick or d-pad |
| Accelerate | W or Up | W | Up | Right trigger, A, or left stick forward |
| Brake / reverse | S or Down | S | Down | Left trigger, B, or left stick back |
| Drift, trick | Shift or Space | Left Shift or Q | Right Shift or Space | Bumpers or X |
| Use item | E, Ctrl, or Enter | E or Left Ctrl | Enter or Right Ctrl | Y |
| Reset kart | R | R | Backspace | Back |
| Pause | Esc | Esc | Esc | Start |

Menus work with the mouse, the arrow keys and Enter, or a controller.

## On the road

- **Drift:** hold drift while turning to charge a boost, then release it. Longer drifts give bigger boosts.
- **Jumps and tricks:** ramps launch the kart. Hold drift as you leave one to roll in the air and get a boost on landing.
- **Coins:** each coin held adds a little top speed, up to ten. A hit scatters three; a fall costs two.
- **Star tokens:** three on every circuit, one high over a jump and two out on the shoulders.
- **Boost pads:** green chevrons on the road.
- **Edges:** striped barriers are safe to lean on. Where there is no barrier there is a drop: open space on Tiny Planet and Prism Run, lava on Lava Crest and Ashfall Gate, cliffs on Frost Peak and Canyon Run, water on Harbor Nights, Palm Cove and Lei Lagoon. Some ramps are followed by a gap in the road. Fall and you are put back a moment later.
- **Items:** Turbo, Triple Turbo, Homing Rocket, Pinball, Oil Slick, Boom Mine, Bubble Shield, Coin Magnet, Shockwave, Overdrive, Skyfall and Thunderclap. The further back you are, the heavier the weapons the crates hand out. **How to play** on the title screen describes each one.

## Online rooms

Pick **Online race** on the title screen. One player hosts and gets a five-letter code or an invite link. Everyone else joins with the code or the link. Up to eight humans, and AI fills the rest of the grid.

Rooms survive refreshes: a reloaded host reclaims the same code, and clients rejoin automatically. A race in progress is not saved, so everyone lands back in the lobby.

### Relay server for tricky networks

Browsers connect to each other directly. That works on most home networks, but players behind strict routers, carrier-grade NAT, cellular data, or Wi-Fi with client isolation need a relay (a TURN server). Free public relays no longer exist, so the game supports a free relay from [Metered](https://www.metered.ca/stun-turn):

1. Create a free Metered account and add an app. The free plan includes 500 MB of relay traffic a month, which is plenty for kart inputs and snapshots.
2. In the app's TURN settings, copy the **credentials URL**. It looks like `https://YOUR-APP.metered.live/api/v1/turn/credentials?apiKey=...`
3. Open `index.html`, find `const TURN_API_URL='';` near the networking section, and paste the URL between the quotes.
4. Commit and push. GitHub Pages redeploys in about a minute.

The lobby shows how each player is connected: local network, direct internet link, or relay server.

## Local development

Serve the folder with any static server and open it in a browser, for example:

```bash
npx serve .
```

Opening the file directly also works for solo and split screen, but online rooms need an `http://` or `https://` address. Browsers won't load the models, textures and lighting files from disk, so the game uses its simpler built-in look when opened that way.

## Models, textures and lighting

The karts and drivers are modelled from real-world measurements (a 125cc race kart and an adult driver in a full-face helmet), along with the items and scenery props, in Blender by a Python script, [`blender/build_assets.py`](blender/build_assets.py), and exported to `assets/kartlands.glb`. The file also carries pivot points (wheels, steering column, hips, neck, shoulders). The game reads them to animate steering, leaning and two-bone arm IK that keeps the hands on the wheel. Each racer's colours and livery (helmet design, race number panel, side-pod stickers) are applied by material name at runtime.

The circuits themselves are built by code. Each is a polygon of corners with a radius and a height (`TRACKS` in `index.html`), rounded into a spline, with ramps, gaps, boost pads and water listed beside it.

To rebuild the models after editing the script, run it with Blender 4.2 or newer:

```bash
blender --background --factory-startup --python blender/build_assets.py
```

Or use the `bpy` module from PyPI (Python 3.11):

```bash
pip install bpy
python blender/build_assets.py
```

Add `-- --blend karts.blend` (or `--blend karts.blend` with plain Python) to also save the scene to open and edit in Blender. You can also paste the script into Blender's Scripting tab and run it there.

The road, ground and rock materials (asphalt, grass, sand, beach, red dirt, snow, basalt, wet pavers, bark, granite, sandstone strata, water ripples) and the alpha-cut foliage cards (pine branches, palm leaves, grass tufts) are procedural Blender shaders and scripted drawings baked into seamless textures by [`blender/build_textures.py`](blender/build_textures.py), which writes a colour map, a normal map and a roughness/occlusion map for each to `assets/textures/`. Run it the same way as the model script.

Photographed materials and skies come from [Poly Haven](https://polyhaven.com) (CC0) through [`blender/fetch_polyhaven.py`](blender/fetch_polyhaven.py), which runs after `build_textures.py` and replaces its procedural road, ground, bark and rock textures with photo-scanned ones:

- **Textures:** colour, normal, and AO/roughness maps, resized for the web, with real-world tile sizes in `assets/textures/tiles.json`.
- **Skies:** for each world, a 1k HDRI for lighting and reflections, a 4k photo of the sky, and a JSON file with the sun direction and colour and the horizon colour measured from the image. The game points its sun where the photo's sun is and fogs the distance to the horizon colour, so shadows, reflections and sky agree.
- **Rocks:** a scanned boulder, decimated to 1,200 triangles in Blender with the full scan's detail baked into a normal map.

The space tracks light from a night HDRI in `assets/hdri/` (Poly Haven, via the [`@pmndrs/assets`](https://www.npmjs.com/package/@pmndrs/assets) package). The Graphics button picks how much post-processing runs: **Sharp** adds ambient occlusion and bloom, **Balanced** keeps bloom, and **Fast** renders plainly for older devices.

## Credits

Built with [three.js](https://threejs.org/), [PeerJS](https://peerjs.com/) and [Blender](https://www.blender.org/). The models and ground textures are generated by the Blender scripts and the tracks by code. Photo-scanned textures, skies and the boulder are CC0 from [Poly Haven](https://polyhaven.com).
