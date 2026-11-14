# Kartlands GP

A 3D arcade derby racer in one HTML file, with models and textures built in Blender. Eight drivers in eight very different vehicles, each with armor and a special weapon of its own; twelve circuits of two to three kilometres with jumps, gaps and long drops; twelve items from crates, coins and star tokens, three Grand Prix cups, AI rivals in three classes, two-player split screen, gamepad support, and online rooms over WebRTC.

**Play it:** https://thedickestrick.github.io/kartlands-gp/

## Modes

- **Grand Prix:** four races for one trophy, with points for every place. Three cups, each at Rookie, Pro or Elite. One or two players.
- **Quick race:** any circuit, any rival class, one, three or five laps. One or two players.
- **Online:** host a room or join one with a five-letter code. Up to eight humans, and rivals fill the rest of the grid.

Coins banked, best laps, star tokens found and trophies won are kept in the browser.

## The grid

| Driver | Ride | Special weapon | In short |
|---|---|---|---|
| Sgt. Havoc | The Bulldog, an armoured 4x4 | **The Fifty:** the roof gun tracks the nearest rival for three seconds | Tough, steady |
| Tiff | Glitterbomb, a pink jeep with rocket pods | **Double Trouble:** two homing rockets | Light, quick off the line |
| Honko | Mister Melty, a janky ice cream truck | **Triple Scoop:** three lobbed scoops that flatten and leave a slick | Bulky all-rounder |
| Scorch | Cinderbox, a hot rod | **Afterburn:** a long boost that sets the road on fire | Fastest, fragile |
| Zorp | The Dish, a flying saucer | **Shrink Ray:** shrinks the two nearest rivals ahead | Agile, floats over oil and the shoulder, thin armor |
| Grubb | Mudslide, a monster truck | **Ground Pound:** hop, land, and everything nearby goes flying | Heavy, shoves everybody |
| Nana Boom | Sweet Pea, a tank | **Main Gun:** one very large shell | Slowest, nearly unstoppable |
| El Turbo | Macho Grande, a muscle car | **Twin Rotaries:** three seconds of lead straight ahead | Quick everywhere |

Every vehicle has its own speed, acceleration, agility, armor and weight. Hits cost armor; at zero the vehicle is wrecked and rebuilt a moment later. Armor mends when you are left alone, and coins patch it up. The special weapon charges with time, and faster with coins, tricks and hits.

## Controls

| Action | Keyboard (solo) | Player 1 (split) | Player 2 (split) | Controller |
|---|---|---|---|---|
| Steer | A / D or arrows | A / D | Left / Right | Either stick or d-pad |
| Accelerate | W or Up | W | Up | A (cross), or left stick forward |
| Brake / reverse | S or Down | S | Down | B (circle), or left stick back |
| Drift, trick | Shift or Space | Left Shift or Q | Right Shift or Space | Bumpers (L1 / R1) |
| Use item | E, Ctrl, or Enter | E or Left Ctrl | Enter or Right Ctrl | Right trigger (R2) |
| Special weapon | F or Q | F | / or . | Left trigger (L2) |
| Back onto the road | R | R | Backspace | Back |
| Pause | Esc | Esc | Esc | Start |

Menus work with the mouse, the arrow keys and Enter, or a controller.

## On the road

- **Drift:** hold drift while turning to charge a boost, then release it. Longer drifts give bigger boosts.
- **Jumps and tricks:** ramps launch you. Hold drift as you leave one to roll in the air and get a boost on landing.
- **Coins:** each coin held adds a little top speed, up to ten. A hit scatters three; a fall costs two, a wreck four.
- **Star tokens:** three on every circuit, one high over a jump and two out on the shoulders.
- **Boost pads:** green chevrons on the road.
- **Edges:** striped barriers are safe to lean on. Where there is no barrier there is a drop: open space on Tiny Planet and Prism Run, lava on Lava Crest and Ashfall Gate, cliffs on Frost Peak and Canyon Run, water on Harbor Nights, Palm Cove and Lei Lagoon. Some ramps are followed by a gap in the road. Fall and you are put back a moment later.
- **Items:** Turbo, Triple Turbo, Homing Rocket, Pinball, Oil Slick, Boom Mine, Bubble Shield, Coin Magnet, Shockwave, Overdrive, Skyfall and Thunderclap. The further back you are, the heavier the weapons the crates hand out. **How to play** on the title screen describes each one.

## Online rooms

Pick **Online race** on the title screen. One player hosts and gets a five-letter code or an invite link. Everyone else joins with the code or the link. Up to eight humans, and AI fills the rest of the grid.

Rooms survive refreshes: a reloaded host reclaims the same code, and clients rejoin automatically. A race in progress is not saved, so everyone lands back in the lobby.

### Relay server for tricky networks

Browsers connect to each other directly. That works on most home networks, but players behind strict routers, carrier-grade NAT, cellular data, or Wi-Fi with client isolation need a relay (a TURN server). Relays cost money to run, so every provider wants an account. The game is wired for the free [Open Relay](https://www.metered.ca/tools/openrelay/) plan from Metered, which includes 20 GB of relay traffic a month. A race sends a few kilobytes a second, so that is thousands of hours.

1. Sign up for the free Open Relay plan and note your app name and API key in the dashboard.
2. Build the **credentials URL** from them: `https://YOUR-APP.metered.live/api/v1/turn/credentials?apiKey=YOUR-API-KEY`
3. Open `index.html`, find `const TURN_API_URL='';` in the networking section, and paste the URL between the quotes.
4. Commit and push. GitHub Pages redeploys in about a minute.

The key sits in the page source by design. It can only hand out relay credentials against your monthly allowance, so treat it as public and never reuse it for anything else.

The Online screen says whether the relay is ready, and the lobby shows how each player is connected: local network, direct internet link, or relay server. If the relay cannot be reached the game falls back to direct connections.

## Local development

Serve the folder with any static server and open it in a browser, for example:

```bash
npx serve .
```

Opening the file directly also works for solo and split screen, but online rooms need an `http://` or `https://` address. Browsers won't load the models, textures and lighting files from disk, so the game uses its simpler built-in look when opened that way, with plain boxes for the vehicles.

## Models, textures and lighting

The eight vehicles and their drivers are modelled in Blender by a Python script, [`blender/build_vehicles.py`](blender/build_vehicles.py), and exported to `assets/vehicles.glb`. Each vehicle is a handful of objects built around their own pivots: the body, the driver's head (which turns with the steering), one wheel placed at every axle, and whatever swivels, kicks or spins (the roof gun, the tank barrel, the saucer's rim, the rotary guns). Colour is painted per face into a vertex colour layer, so the whole grid shares five materials: paint, matte, metal, glow and glass.

The item crates, rockets and scenery props (trees, palms, cacti, rocks, crystals) come from [`blender/build_assets.py`](blender/build_assets.py), exported to `assets/kartlands.glb`.

To rebuild either file after editing its script, run it with Blender 4.2 or newer:

```bash
blender --background --factory-startup --python blender/build_vehicles.py
```

Or use the `bpy` module from PyPI:

```bash
pip install bpy
python blender/build_vehicles.py
```

Add `-- --blend vehicles.blend` (or `--blend vehicles.blend` with plain Python) to also save the scene to open and edit in Blender. You can also paste a script into Blender's Scripting tab and run it there.

The circuits themselves are built by code. Each is a polygon of corners with a radius and a height (`TRACKS` in `index.html`), rounded into a spline, with ramps, gaps, boost pads and water listed beside it.

The road, ground and rock materials (asphalt, grass, sand, beach, red dirt, snow, basalt, wet pavers, bark, granite, sandstone strata, water ripples) and the alpha-cut foliage cards (pine branches, palm leaves, grass tufts) are procedural Blender shaders and scripted drawings baked into seamless textures by [`blender/build_textures.py`](blender/build_textures.py), which writes a colour map, a normal map and a roughness/occlusion map for each to `assets/textures/`. Run it the same way as the model script.

Photographed materials and skies come from [Poly Haven](https://polyhaven.com) (CC0) through [`blender/fetch_polyhaven.py`](blender/fetch_polyhaven.py), which runs after `build_textures.py` and replaces its procedural road, ground, bark and rock textures with photo-scanned ones:

- **Textures:** colour, normal, and AO/roughness maps, resized for the web, with real-world tile sizes in `assets/textures/tiles.json`.
- **Skies:** for each world, a 1k HDRI for lighting and reflections, a 4k photo of the sky, and a JSON file with the sun direction and colour and the horizon colour measured from the image. The game points its sun where the photo's sun is and fogs the distance to the horizon colour, so shadows, reflections and sky agree.
- **Rocks:** a scanned boulder, decimated to 1,200 triangles in Blender with the full scan's detail baked into a normal map.

The space tracks light from a night HDRI in `assets/hdri/` (Poly Haven, via the [`@pmndrs/assets`](https://www.npmjs.com/package/@pmndrs/assets) package). The Graphics button picks how much post-processing runs: **Sharp** adds ambient occlusion and bloom, **Balanced** keeps bloom, and **Fast** renders plainly for older devices.

## Credits

Built with [three.js](https://threejs.org/), [PeerJS](https://peerjs.com/) and [Blender](https://www.blender.org/). The vehicles, drivers, props and ground textures are generated by the Blender scripts and the tracks by code. Photo-scanned textures, skies and the boulder are CC0 from [Poly Haven](https://polyhaven.com).
