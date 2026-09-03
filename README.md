# Kartlands GP

A 3D arcade kart racer in a single HTML file. Eight racers, twelve circuits, drifting, items, AI rivals, two-player split screen, gamepad support, and online rooms over WebRTC.

**Play it:** https://thedickestrick.github.io/kartlands-gp/

## Controls

| Action | Keyboard (solo) | Player 1 (split) | Player 2 (split) | Controller |
|---|---|---|---|---|
| Steer | A / D or arrows | A / D | Left / Right | Either stick or d-pad |
| Accelerate | W or Up | W | Up | Right trigger, A, or left stick forward |
| Brake / reverse | S or Down | S | Down | Left trigger, B, or left stick back |
| Drift | Shift or Space | Left Shift or Q | Right Shift or Space | Bumpers or X |
| Use item | E, Ctrl, or Enter | E or Left Ctrl | Enter or Right Ctrl | Y |
| Reset kart | R | R | Backspace | Back |
| Pause | Esc | Esc | Esc | Start |

Hold drift while turning to charge a boost, then release it. Longer drifts give bigger boosts.

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

Opening the file directly also works for solo and split screen, but online rooms need an `http://` or `https://` address.

## Credits

Built with [three.js](https://threejs.org/) and [PeerJS](https://peerjs.com/). All art is procedural and original.
