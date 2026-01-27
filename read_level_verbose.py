import struct
import math
import sys
import re
import json
import time
from datetime import datetime
from pathlib import Path

# --- LOGGING SETUP ---
class Logger:
    def __init__(self, log_path=None, verbose_console=False):
        self.log_file = None
        self.verbose_console = verbose_console
        if log_path:
            self.log_file = open(log_path, 'w', encoding='utf-8')
    
    def log(self, message):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        full_message = f"{timestamp} {message}"
        if self.verbose_console:
            print(full_message)
        if self.log_file:
            self.log_file.write(full_message + '\n')
            self.log_file.flush()

    def close(self):
        if self.log_file:
            self.log_file.close()

# Initial logger
logger = Logger()

# Check for CLI argument
if len(sys.argv) < 2:
    print("Usage: python read_level_verbose.py <level_file>")
    print("Example: python read_level_verbose.py levels/dino5.bin")
    sys.exit(1)

input_path = Path(sys.argv[1])
if input_path.suffix.lower() == '.bin':
    bin_file = input_path
else:
    bin_file = input_path.with_suffix('.bin')

if not bin_file.exists():
    print(f"Error: File not found: {bin_file}")
    sys.exit(1)

level_name = bin_file.stem
output_file = Path(f"{level_name}_data.json")
# Set up verbose log file
logger = Logger(output_file.parent / f"{level_name}_read_verbose.log")
max_string_len = 1_000_000
start_time = time.time()

with open(bin_file, 'rb') as f:
    f.seek(0, 2)
    f_size = f.tell()
    f.seek(0)
    logger.log(f"Opened {bin_file.name}, size: {f_size} bytes")
    
    # First two int32 values
    pos = f.tell()
    dummy_bytes = f.read(4)
    dummy = struct.unpack('<i', dummy_bytes)[0]
    logger.log(f"0x{pos:X}: read int32 (dummy) = {dummy} from bytes {dummy_bytes.hex()}")

    pos = f.tell()
    tt_count_bytes = f.read(4)
    tile_type_count = struct.unpack('<i', tt_count_bytes)[0]
    logger.log(f"0x{pos:X}: read int32 (tileTypeCount) = {tile_type_count} from bytes {tt_count_bytes.hex()}")

    strings = []
    logger.log(f"Reading {tile_type_count} tile strings...")
    for i in range(tile_type_count):
        pos = f.tell()
        length_bytes = f.read(4)
        length = struct.unpack('<i', length_bytes)[0]
        string_bytes = f.read(length)
        val = string_bytes.decode('ascii').rstrip('\x00')
        logger.log(f"  0x{pos:X}: TileString[{i}] len={length} val='{val}' bytes={length_bytes.hex()}+{string_bytes.hex()}")
        strings.append({"length": length, "value": val})

    pos = f.tell()
    layer_count_bytes = f.read(4)
    layer_count = struct.unpack('<i', layer_count_bytes)[0]
    logger.log(f"0x{pos:X}: read int32 (layerCount) = {layer_count} from bytes {layer_count_bytes.hex()}")

    layers = []
    for layer_idx in range(layer_count):
        logger.log(f"--- START LAYER {layer_idx + 1} ---")
        layer = {'layer': layer_idx + 1}
        
        pos = f.tell()
        wall_count_bytes = f.read(4)
        wall_count = struct.unpack('<i', wall_count_bytes)[0]
        logger.log(f"0x{pos:X}: Layer {layer_idx+1} wallCount = {wall_count} (bytes {wall_count_bytes.hex()})")
        
        walls = []
        for i in range(wall_count):
            w_pos = f.tell()
            w_bytes = f.read(32) # 4 doubles
            px, py, w, l = struct.unpack('<dddd', w_bytes)
            
            sl_pos = f.tell()
            sl_bytes = f.read(4)
            sl = struct.unpack('<i', sl_bytes)[0]
            sn_bytes = f.read(sl)
            sn = sn_bytes.decode('ascii').rstrip('\x00')
            
            flag_pos = f.tell()
            flag_byte = f.read(1)
            flag = flag_byte[0]
            logger.log(f"  Wall {i} at 0x{w_pos:X}: type='{sn}', pos=({px}, {py}), w={w}, l={l}, shape_flag={flag}")
            
            shapes = []
            if flag == 0:
                sc_pos = f.tell()
                sc_bytes = f.read(4)
                sc = struct.unpack('<i', sc_bytes)[0]
                logger.log(f"    0x{sc_pos:X}: Wall {i} shapeCount = {sc}")
                for j in range(sc):
                    sh_pos = f.tell()
                    ssh_len = struct.unpack('<i', f.read(4))[0]
                    ssh_name = f.read(ssh_len).decode('ascii').rstrip('\x00')
                    if ssh_name == "Circle":
                        c_data = f.read(24)
                        cx, cy, r = struct.unpack('<ddd', c_data)
                        shapes.append({"shape_type_name": "Circle", "data": {"type": "Circle", "center_x": cx, "center_y": cy, "radius": r}})
                        logger.log(f"      0x{sh_pos:X}: Shape {j} Circle: ({cx}, {cy}) r={r}")
                    else:
                        nv = struct.unpack('<i', f.read(4))[0]
                        verts = [struct.unpack('<dd', f.read(16)) for _ in range(nv)]
                        shapes.append({"shape_type_name": ssh_name, "data": {"type": "ConPoly", "num_vertices": nv, "vertices": verts}})
                        logger.log(f"      0x{sh_pos:X}: Shape {j} {ssh_name} with {nv} vertices")
            
            res = struct.unpack('<i', f.read(4))[0]
            wid = struct.unpack('<i', f.read(4))[0]
            walls.append({
                "pos_x": px, "pos_y": py, "position": [px, py], "width": w, "length": l,
                "wall_type_name": sn, "has_shapes_flag": flag, "shapes": shapes,
                "reserved": res, "wall_id": wid
            })

        pos = f.tell()
        pc_bytes = f.read(4)
        path_count = struct.unpack('<i', pc_bytes)[0]
        logger.log(f"0x{pos:X}: Layer {layer_idx+1} pathCount = {path_count}")
        paths = []
        for i in range(path_count):
            p_pos = f.tell()
            sl = struct.unpack('<i', f.read(4))[0]
            pn = f.read(sl).decode('ascii').rstrip('\x00')
            px, py = struct.unpack('<dd', f.read(16))
            ex, ey = struct.unpack('<dd', f.read(16))
            pf = f.read(1)[0]
            path = {"path_name": pn, "position": [px, py], "extent_x_guess": ex, "extent_y_guess": ey, "path_flag": pf}
            logger.log(f"  0x{p_pos:X}: Path {i} '{pn}' pos=({px},{py}) flag={pf}")
            if pf == 1:
                pt_c = struct.unpack('<i', f.read(4))[0]
                pts = []
                for j in range(pt_c):
                    v = struct.unpack('<dddddd', f.read(48))
                    pts.append({"p0": [v[0], v[1]], "p1": [v[2], v[3]], "p2": [v[4], v[5]]})
                path["point_count"] = pt_c
                path["spline_points"] = pts
            path["internal_id_guess"] = struct.unpack('<i', f.read(4))[0]
            paths.append(path)

        pos = f.tell()
        ec_bytes = f.read(4)
        entity_count = struct.unpack('<i', ec_bytes)[0]
        logger.log(f"0x{pos:X}: Layer {layer_idx+1} entityCount = {entity_count}")
        entities = []
        lastX, lastY, lastPrio = 0.0, 0.0, 0
        for i in range(entity_count):
            e_pos = f.tell()
            sl = struct.unpack('<i', f.read(4))[0]
            et = f.read(sl).decode('ascii').rstrip('\x00')
            dx, dy = struct.unpack('<ii', f.read(8))
            lastX += dx; lastY += dy
            logger.log(f"  0x{e_pos:X}: Entity {i} '{et}' dx={dx}, dy={dy} -> ({lastX*0.01}, {lastY*0.01})")
            
            f158, f15c = struct.unpack('<ii', f.read(8))
            vx, vy = struct.unpack('<ii', f.read(8))
            f250, rot = struct.unpack('<ii', f.read(8))
            hb = f.read(1)[0]
            ent = {
                "type": et, "position": [lastX * 0.01, lastY * 0.01],
                "field_158": f158, "field_15c": f15c,
                "vec": {"raw": [vx, vy], "scaled": [vx*0.01, vy*0.01]},
                "field_250": {"raw": f250, "scaled": f250*0.01},
                "rotation": {"raw": rot, "scaled": rot*0.01},
                "has_box": hb
            }
            if hb != 0:
                en = struct.unpack('<i', f.read(4))[0]
                b = struct.unpack('<iiii', f.read(16))
                ent["box"] = {"enabled": en, "bounds": list(b)}
            
            ent["color"] = {"rgba": list(f.read(4))}
            ent["mass"] = struct.unpack('<d', f.read(8))[0]
            p_delta = struct.unpack('<i', f.read(4))[0]
            lastPrio += p_delta
            ent["priority"] = lastPrio
            
            hm = struct.unpack('<i', f.read(4))[0]
            ent["has_move_direction"] = hm
            if hm == 1:
                mv = struct.unpack('<ddi dddddd', f.read(68))
                ent["move_direction"] = {"v0": mv[0], "v1": mv[1], "flag0": mv[2], "v2": mv[3], "v3": mv[4], "v4": mv[5], "v5": mv[6], "v6": mv[7], "v7": mv[8]}
            
            hp = struct.unpack('<i', f.read(4))[0]
            ent["has_path_follow"] = hp
            if hp == 1:
                v0, v1 = struct.unpack('<dd', f.read(16))
                f0 = struct.unpack('<i', f.read(4))[0]
                v2, v3 = struct.unpack('<dd', f.read(16))
                psl = struct.unpack('<i', f.read(4))[0]
                pn = f.read(psl).decode('ascii').rstrip('\x00')
                f1, mode = struct.unpack('<ii', f.read(8))
                v4 = struct.unpack('<d', f.read(8))[0]
                ent["path_follow"] = {"v0": v0, "v1": v1, "flag0": f0, "v2": v2, "v3": v3, "path_name": pn, "flag1": f1, "mode": mode, "v4": v4}
            
            he = struct.unpack('<i', f.read(4))[0]
            ent["has_emitter"] = he
            if he == 1:
                ev = struct.unpack('<ddddddddddd', f.read(88))
                ed = {f"v{j}": ev[j] for j in range(11)}
                if layer_idx >= 3:
                    ed["reserved"], ed["end_marker"] = struct.unpack('<ii', f.read(8))
                ent["emitter"] = ed
            entities.append(ent)

        pos = f.tell()
        dc_bytes = f.read(4)
        deco_count = struct.unpack('<i', dc_bytes)[0]
        logger.log(f"0x{pos:X}: Layer {layer_idx+1} decoCount = {deco_count}")
        decorations = []
        lastX, lastY, lastPrio = 0.0, 0.0, 0
        for i in range(deco_count):
            d_pos = f.tell()
            dt = f.read(1)[0]
            deco = {"type": dt}
            if dt == 2:
                sl = struct.unpack('<i', f.read(4))[0]
                deco["string"] = f.read(sl).decode('ascii').rstrip('\x00')
            elif dt == 1:
                deco["cell"] = struct.unpack('<i', f.read(4))[0]
            
            dx, dy = struct.unpack('<ii', f.read(8))
            lastX += dx; lastY += dy
            deco["position"] = [lastX * 0.01, lastY * 0.01]
            sz = struct.unpack('<i', f.read(4))[0]
            deco["size"] = {"raw": sz, "scaled": sz*0.01}
            ef = f.read(1)[0]
            deco["extra_flag"] = ef
            
            if ef != 0:
                deco["extra_bools"] = list(f.read(2))
                deco["extra_ints"] = list(struct.unpack('<iiii', f.read(16)))
                so = struct.unpack('<i', f.read(4))[0]
                deco["size_override"] = {"raw": so, "scaled": so*0.01}
                deco["extra_unknown"] = struct.unpack('<h', f.read(2))[0]
            
            deco["color_rgba"] = list(f.read(4))
            wr, hr = struct.unpack('<ii', f.read(8))
            deco["dimensions"] = {"raw": [wr, hr], "scaled": [wr*0.01, hr*0.01]}
            dp = struct.unpack('<i', f.read(4))[0]
            lastPrio += dp
            deco["priority"] = {"total": lastPrio}
            logger.log(f"  0x{d_pos:X}: Deco {i} type={dt} dx={dx}, dy={dy} prio_delta={dp}")
            decorations.append(deco)
        
        layers.append({
            "layer": layer_idx+1, "wall_count": wall_count, "walls": walls,
            "path_count": path_count, "paths": paths,
            "entity_count": entity_count, "entities": entities,
            "decoration_count": deco_count, "decorations": decorations
        })

output_data = {"dummy": dummy, "tileTypeCount": tile_type_count, "tileTypes": strings, "layerCount": layer_count, "layers": layers}
with open(output_file, 'w') as out:
    json.dump(output_data, out, indent=2)

duration = time.time() - start_time
logger.log(f"Finished. JSON saved to {output_file}")
logger.log(f"Total time: {duration:.4f} seconds ({duration * 1000:.2f} ms)")
logger.close()
