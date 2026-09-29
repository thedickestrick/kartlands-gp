"""Download photo-scanned textures and sky HDRIs from Poly Haven (CC0) and prepare them for Kartlands GP.

Run it after build_textures.py (it overwrites the procedural ground, road, bark and rock textures
with photographed ones), with Blender or the bpy module:
    blender --background --factory-startup --python blender/fetch_polyhaven.py
    python blender/fetch_polyhaven.py [--only textures|skies|rocks]

Textures land in assets/textures/ as NAME_c.jpg (colour), NAME_n.jpg (OpenGL normal) and NAME_r.jpg
(AO / roughness / metal), plus tiles.json with each texture's real-world size in metres.

Skies land in assets/sky/: WORLD_env.exr (1k HDR for lighting and reflections), WORLD_bg.jpg (the upper
hemisphere at 4k, pre-exposed, for the visible sky) and WORLD.json with the sun direction and colour
and the horizon colour, all measured from the HDRI so the game's sun and fog match the photo.
"""
import json
import math
import os
import sys
import tempfile
import urllib.request

import bpy  # must come first: the PyPI bpy module needs it before numpy-heavy work
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
ASSETS = os.path.join(HERE, '..', 'assets')
UA = {'User-Agent': 'KartlandsGP-asset-build/1.0 (+https://github.com/thedickestrick/kartlands-gp)'}

# game name -> (Poly Haven id, resolution)
TEXTURES = {
    'asphalt': ('asphalt_track', '2k'),
    'grass': ('leafy_grass', '1k'),
    'sand': ('aerial_beach_01', '2k'),
    'beach': ('coast_sand_01', '2k'),
    'dirt': ('cracked_red_ground', '1k'),
    'snow': ('snow_02', '1k'),
    'basalt': ('burned_ground_01', '1k'),
    'pavers': ('concrete_pavers', '1k'),
    'bark': ('pine_bark', '1k'),
    'palmbark': ('palm_bark', '1k'),
    'rock': ('rock_face', '1k'),
    'cliff': ('cliff_side', '1k'),
    'darkrock': ('dark_rock', '1k'),
}

# JPEG settings for the web: large-area colour maps stay 2k, everything else is 1k
BIG_COLOR = {'asphalt', 'sand', 'beach'}


def reencode(path, size, quality):
    """Resize a downloaded JPEG to at most size x size and re-save it at the given quality."""
    img = bpy.data.images.load(path)
    if img.size[0] > size:
        img.scale(size, size)
    img.file_format = 'JPEG'
    img.save(filepath=path, quality=quality)
    bpy.data.images.remove(img)


# world id -> (Poly Haven HDRI, draw it as the visible sky?)
SKIES = {
    'sunny': ('kloofendal_48d_partly_cloudy_puresky', True),
    'desert': ('syferfontein_18d_clear_puresky', True),
    'frost': ('snow_field_puresky', True),
    'harbor': ('shanghai_bund', True),
    'lava': ('the_sky_is_on_fire', False),
    'cove': ('kloofendal_38d_partly_cloudy_puresky', True),
    'canyon': ('qwantani_afternoon_puresky', True),
    'lagoon': ('kloppenheim_06_puresky', True),
    'ashfall': ('industrial_sunset_02_puresky', False),
    'portals': ('wasteland_clouds_puresky', True),
}
BG_WIDTH = 4096
BG_BELOW = math.radians(6)   # keep a band below the horizon for hills and low camera angles


def api(path):
    return json.load(urllib.request.urlopen(urllib.request.Request('https://api.polyhaven.com/' + path, headers=UA)))


def download(url, path):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req) as r, open(path, 'wb') as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return path


def fetch_textures():
    out = os.path.join(ASSETS, 'textures')
    os.makedirs(out, exist_ok=True)
    tiles = {}
    for name, (pid, res) in TEXTURES.items():
        files = api('files/' + pid)
        info = api('info/' + pid)
        for key, suffix in (('Diffuse', 'c'), ('nor_gl', 'n'), ('arm', 'r')):
            r = res if key != 'arm' else '1k'
            path = download(files[key][r]['jpg']['url'], os.path.join(out, f'{name}_{suffix}.jpg'))
            reencode(path, 2048 if (suffix == 'c' and name in BIG_COLOR) else 1024, 90 if suffix == 'n' else 82)
        tiles[name] = round(info['dimensions'][0] / 1000, 3)
        print(f'{name}: {pid} {res}, {tiles[name]} m per tile')
    with open(os.path.join(out, 'tiles.json'), 'w') as f:
        json.dump(tiles, f, indent=1)


def load_hdr(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[:, :, :3]   # rows run bottom-up, like three.js equirect v


def directions(h, w):
    v = (np.arange(h) + .5) / h
    u = (np.arange(w) + .5) / w
    el = (v - .5) * math.pi
    az = (u - .5) * 2 * math.pi
    return el, az


def save_image(arr, path, fmt, **settings):
    h, w = arr.shape[:2]
    img = bpy.data.images.new('out', w, h, float_buffer=(fmt == 'OPEN_EXR'))
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(np.concatenate([arr, np.ones((h, w, 1), np.float32)], 2).astype(np.float32).ravel())
    scene = bpy.context.scene
    s = scene.render.image_settings
    s.file_format = fmt
    s.color_mode = 'RGB'
    for k, val in settings.items():
        setattr(s, k, val)
    scene.view_settings.view_transform = 'Standard'
    img.save_render(path, scene=scene)
    bpy.data.images.remove(img)


def srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def fetch_skies():
    out = os.path.join(ASSETS, 'sky')
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp()
    for world, (pid, background) in SKIES.items():
        files = api('files/' + pid)['hdri']
        # lighting: 1k HDR, stored as half-float EXR
        env = load_hdr(download(files['1k']['hdr']['url'], os.path.join(tmp, 'env.hdr')))
        env = np.nan_to_num(env, nan=0, posinf=0)
        save_image(np.clip(env, 0, 200), os.path.join(out, world + '_env.exr'), 'OPEN_EXR', color_depth='16', exr_codec='ZIP')
        # measure the sun: centroid of the brightest 0.05% of the 1k image
        h, w = env.shape[:2]
        lum = env @ np.array([.2126, .7152, .0722], np.float32)
        el, az = directions(h, w)
        cut = np.quantile(lum, .9995)
        mask = lum >= cut
        wgt = lum * mask
        E, A = np.meshgrid(el, az, indexing='ij')
        dx = (np.cos(E) * np.cos(A) * wgt).sum()
        dy = (np.sin(E) * wgt).sum()
        dz = (np.cos(E) * np.sin(A) * wgt).sum()
        sun = np.array([dx, dy, dz])
        sun /= np.linalg.norm(sun)
        sun_rgb = (env[mask] * lum[mask, None]).sum(0) / lum[mask].sum()
        sun_rgb = sun_rgb / sun_rgb.max()
        band = (el > math.radians(1)) & (el < math.radians(6))
        horizon = env[band].reshape(-1, 3).mean(0)
        meta = {'hdri': pid, 'sun': [round(float(x), 4) for x in sun], 'sunColor': [round(float(x), 4) for x in sun_rgb],
                'horizon': [round(float(x), 5) for x in horizon], 'envMean': round(float(lum.mean()), 5)}
        if background:
            bg = load_hdr(download(files['4k']['hdr']['url'], os.path.join(tmp, 'bg.hdr')))
            bg = np.nan_to_num(bg, nan=0, posinf=0)
            H, W = bg.shape[:2]
            row0 = int((.5 - BG_BELOW / math.pi) * H)
            upper = bg[row0:]
            # expose so the bright sky (not the sun disc) sits just under white; the game scales it back up
            ul = upper @ np.array([.2126, .7152, .0722], np.float32)
            scale = .85 / max(float(np.quantile(ul, .985)), 1e-4)
            step = max(1, W // BG_WIDTH)
            save_image(srgb(upper[::step, ::step] * scale), os.path.join(out, world + '_bg.jpg'), 'JPEG', quality=86)
            meta.update({'bgScale': round(scale, 5), 'bgBelow': round(BG_BELOW, 5)})
            os.remove(os.path.join(tmp, 'bg.hdr'))
        with open(os.path.join(out, world + '.json'), 'w') as f:
            json.dump(meta, f, indent=1)
        print(world, pid, 'sun', meta['sun'], 'elev', round(math.degrees(math.asin(meta['sun'][1])), 1))


# game name -> (Poly Haven model, triangle budget)
ROCKS = {'boulder': ('namaqualand_boulder_05', 1200)}


def fetch_rocks():
    """Import a scanned rock, normalise it to ~1.2 m radius, decimate it, and bake the scan's detail
    into a normal map for the low-poly version. Writes assets/models/NAME.glb and NAME_c/_n/_r.jpg."""
    models, textures = os.path.join(ASSETS, 'models'), os.path.join(ASSETS, 'textures')
    os.makedirs(models, exist_ok=True)
    for name, (pid, budget) in ROCKS.items():
        bpy.ops.wm.read_factory_settings(use_empty=True)
        g = api('files/' + pid)['gltf']['1k']['gltf']
        d = tempfile.mkdtemp()
        path = download(g['url'], os.path.join(d, g['url'].rsplit('/', 1)[1]))
        for rel, meta in g['include'].items():
            os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
            download(meta['url'], os.path.join(d, rel))
        bpy.ops.import_scene.gltf(filepath=path)
        meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
        with bpy.context.temp_override(active_object=meshes[0], selected_editable_objects=meshes, selected_objects=meshes):
            bpy.ops.object.join()
        hi = meshes[0]
        hi.data.transform(hi.matrix_world)
        hi.matrix_world = Matrix()
        co = np.empty(len(hi.data.vertices) * 3, np.float32)
        hi.data.vertices.foreach_get('co', co)
        co = co.reshape(-1, 3)
        lo_b, hi_b = co.min(0), co.max(0)
        centre = (lo_b + hi_b) / 2
        k = 1.2 / max((hi_b[0] - lo_b[0]) / 2, (hi_b[1] - lo_b[1]) / 2)
        hi.data.transform(Matrix.Scale(k, 4) @ Matrix.Translation(-Vector(centre)))
        # low-poly copy through a Decimate modifier; collapse keeps the UV layout, so the scan's colour map still fits
        tris = sum(len(p.vertices) - 2 for p in hi.data.polygons)
        lo = hi.copy()
        lo.data = hi.data.copy()
        bpy.context.scene.collection.objects.link(lo)
        mod = lo.modifiers.new('dec', 'DECIMATE')
        mod.ratio = min(1.0, budget / tris)
        dg = bpy.context.evaluated_depsgraph_get()
        low_mesh = bpy.data.meshes.new_from_object(lo.evaluated_get(dg))
        lo.modifiers.clear()
        lo.data = low_mesh
        for poly in lo.data.polygons:
            poly.use_smooth = True
        # bake high -> low tangent-space normals into a 1k image
        img = bpy.data.images.new(name + '_n', 1024, 1024)
        img.colorspace_settings.name = 'Non-Color'
        mat = bpy.data.materials.new('bake')
        mat.use_nodes = True
        node = mat.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = img
        mat.node_tree.nodes.active = node
        lo.data.materials.clear()
        lo.data.materials.append(mat)
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 4
        bpy.ops.object.select_all(action='DESELECT')
        hi.select_set(True)
        lo.select_set(True)
        bpy.context.view_layer.objects.active = lo
        bpy.ops.object.bake(type='NORMAL', use_selected_to_active=True, cage_extrusion=.03, max_ray_distance=.2, margin=8)
        img.file_format = 'JPEG'
        img.save(filepath=os.path.join(textures, name + '_n.jpg'), quality=90)
        for key, suffix in (('diff', 'c'), ('arm', 'r')):
            src = next(os.path.join(d, rel) for rel in g['include'] if f'_{key}_' in rel)
            dst = os.path.join(textures, f'{name}_{suffix}.jpg')
            with open(src, 'rb') as a, open(dst, 'wb') as b:
                b.write(a.read())
            reencode(dst, 1024, 82)
        # export only the low-poly mesh, geometry and UVs
        bpy.ops.object.select_all(action='DESELECT')
        lo.select_set(True)
        lo.name = name
        bpy.ops.export_scene.gltf(filepath=os.path.join(models, name + '.glb'), export_format='GLB', use_selection=True,
                                  export_yup=True, export_texcoords=True, export_normals=True, export_materials='NONE')
        print(f'{name}: {pid}, {tris} -> {sum(len(p.vertices) - 2 for p in lo.data.polygons)} triangles')


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    only = argv[argv.index('--only') + 1] if '--only' in argv else None
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if only in (None, 'textures'):
        fetch_textures()
    if only in (None, 'skies'):
        fetch_skies()
    if only in (None, 'rocks'):
        fetch_rocks()


if __name__ == '__main__':
    main()
