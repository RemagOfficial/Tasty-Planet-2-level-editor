import struct
import math
import sys
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

def write_string(f, s):
    pos = f.tell()
    # Game expects null terminator in the length-prefixed bytes
    bytes_val = s.encode('ascii') + b'\x00'
    length = len(bytes_val)
    length_bytes = struct.pack('<i', length)
    f.write(length_bytes)
    f.write(bytes_val)
    logger.log(f"  0x{pos:X}: Wrote string '{s}' (len {length}) bytes: {length_bytes.hex()} + {bytes_val.hex()}")

# Check for CLI argument
if len(sys.argv) < 2:
    print("Usage: python write_level_verbose.py <level_data.json>")
    print("Example: python write_level_verbose.py dino5_data.json")
    sys.exit(1)

json_path = Path(sys.argv[1])
if not json_path.exists():
    print(f"Error: File not found: {json_path}")
    sys.exit(1)

with open(json_path, 'r') as jf:
    data = json.load(jf)

# Cleaned up log filename: [level]_rebuilt_verbose.log
level_name = json_path.name.replace("_data.json", "")
output_bin = Path(json_path.parent / f"{level_name}_rebuilt_verbose.bin")
logger = Logger(output_bin.parent / f"{level_name}_rebuilt_verbose.log")
start_time = time.time()

with open(output_bin, 'wb') as f:
    logger.log(f"Writing to {output_bin.name}...")
    
    # Header
    pos = f.tell()
    dummy_bytes = struct.pack('<i', data['dummy'])
    f.write(dummy_bytes)
    logger.log(f"0x{pos:X}: Wrote int32 (dummy) = {data['dummy']} (bytes {dummy_bytes.hex()})")

    pos = f.tell()
    count_bytes = struct.pack('<i', data['tileTypeCount'])
    f.write(count_bytes)
    logger.log(f"0x{pos:X}: Wrote int32 (tileTypeCount) = {data['tileTypeCount']} (bytes {count_bytes.hex()})")

    # Tile Types
    for i, tt in enumerate(data['tileTypes']):
        write_string(f, tt['value'])

    # Layer Count
    pos = f.tell()
    lc_bytes = struct.pack('<i', data['layerCount'])
    f.write(lc_bytes)
    logger.log(f"0x{pos:X}: Wrote int32 (layerCount) = {data['layerCount']}")

    for layer_idx, layer in enumerate(data['layers']):
        logger.log(f"--- START LAYER {layer_idx + 1} ---")
        
        # Wall Count
        pos = f.tell()
        wc_bytes = struct.pack('<i', layer['wall_count'])
        f.write(wc_bytes)
        logger.log(f"0x{pos:X}: Wrote wallCount = {layer['wall_count']}")

        for i, wall in enumerate(layer['walls']):
            w_pos = f.tell()
            w_bytes = struct.pack('<dddd', wall['pos_x'], wall['pos_y'], wall['width'], wall['length'])
            f.write(w_bytes)
            logger.log(f"  Wall {i} at 0x{w_pos:X}: pos=({wall['pos_x']}, {wall['pos_y']})")
            
            write_string(f, wall['wall_type_name'])
            
            flag_pos = f.tell()
            f.write(bytes([wall['has_shapes_flag']]))
            logger.log(f"    0x{flag_pos:X}: Wrote has_shapes_flag = {wall['has_shapes_flag']}")
            
            if wall['has_shapes_flag'] == 0:
                pos = f.tell()
                sc_bytes = struct.pack('<i', len(wall['shapes']))
                f.write(sc_bytes)
                logger.log(f"    0x{pos:X}: Wrote shape_count = {len(wall['shapes'])}")
                for shape in wall['shapes']:
                    write_string(f, shape['shape_type_name'])
                    if shape['shape_type_name'] == "Circle":
                        d = shape['data']
                        f.write(struct.pack('<ddd', d['center_x'], d['center_y'], d['radius']))
                    else:
                        d = shape['data']
                        f.write(struct.pack('<i', len(d['vertices'])))
                        for v in d['vertices']:
                            f.write(struct.pack('<dd', v[0], v[1]))
            
            f.write(struct.pack('<ii', wall['reserved'], wall['wall_id']))

        # Path Count
        pos = f.tell()
        pc_bytes = struct.pack('<i', layer['path_count'])
        f.write(pc_bytes)
        logger.log(f"0x{pos:X}: Wrote pathCount = {layer['path_count']}")

        for i, path in enumerate(layer['paths']):
            p_pos = f.tell()
            write_string(f, path['path_name'])
            f.write(struct.pack('<ddddB', path['position'][0], path['position'][1], path['extent_x_guess'], path['extent_y_guess'], path['path_flag']))
            if path['path_flag'] == 1:
                f.write(struct.pack('<i', path['point_count']))
                for pt in path['spline_points']:
                    f.write(struct.pack('<dddddd', pt['p0'][0], pt['p0'][1], pt['p1'][0], pt['p1'][1], pt['p2'][0], pt['p2'][1]))
            f.write(struct.pack('<i', path.get('internal_id_guess', 0)))

        # Entity Count
        pos = f.tell()
        ec_bytes = struct.pack('<i', layer['entity_count'])
        f.write(ec_bytes)
        logger.log(f"0x{pos:X}: Wrote entityCount = {layer['entity_count']}")

        lastX, lastY, lastPrio = 0.0, 0.0, 0
        for i, ent in enumerate(layer['entities']):
            e_pos = f.tell()
            write_string(f, ent['type'])
            
            currX_int = int(round(ent['position'][0] * 100))
            currY_int = int(round(ent['position'][1] * 100))
            dx = currX_int - int(round(lastX))
            dy = currY_int - int(round(lastY))
            lastX = float(currX_int)
            lastY = float(currY_int)
            
            f.write(struct.pack('<ii', dx, dy))
            f.write(struct.pack('<ii', ent['field_158'], ent['field_15c']))
            f.write(struct.pack('<ii', ent['vec']['raw'][0], ent['vec']['raw'][1]))
            f.write(struct.pack('<ii', ent['field_250']['raw'], ent['rotation']['raw']))
            
            hb = ent['has_box']
            f.write(bytes([hb]))
            if hb != 0:
                box = ent['box']
                f.write(struct.pack('<i', box['enabled']))
                f.write(struct.pack('<iiii', *box['bounds']))
            
            f.write(bytes(ent['color']['rgba']))
            f.write(struct.pack('<d', ent['mass']))
            
            p_delta = ent['priority'] - lastPrio
            f.write(struct.pack('<i', p_delta))
            lastPrio = ent['priority']
            
            # move_direction
            hm = ent['has_move_direction']
            f.write(struct.pack('<i', hm))
            if hm == 1:
                md = ent['move_direction']
                f.write(struct.pack('<ddi dddddd', md['v0'], md['v1'], md['flag0'], md['v2'], md['v3'], md['v4'], md['v5'], md['v6'], md['v7']))
            
            # path_follow
            hp = ent['has_path_follow']
            f.write(struct.pack('<i', hp))
            if hp == 1:
                pf = ent['path_follow']
                f.write(struct.pack('<ddi dd', pf['v0'], pf['v1'], pf['flag0'], pf['v2'], pf['v3']))
                write_string(f, pf['path_name'])
                f.write(struct.pack('<ii d', pf['flag1'], pf['mode'], pf['v4']))
            
            # emitter
            he = ent['has_emitter']
            f.write(struct.pack('<i', he))
            if he == 1:
                em = ent['emitter']
                f.write(struct.pack('<ddddddddddd', em['v0'], em['v1'], em['v2'], em['v3'], em['v4'], em['v5'], em['v6'], em['v7'], em['v8'], em['v9'], em['v10']))
                if layer_idx >= 3:
                    f.write(struct.pack('<ii', em.get('reserved', 0), em.get('end_marker', 0)))
            
            logger.log(f"  0x{e_pos:X}: Wrote Entity {i} '{ent['type']}' dx={dx}, dy={dy}")

        # Decoration Count
        pos = f.tell()
        dc_bytes = struct.pack('<i', layer['decoration_count'])
        f.write(dc_bytes)
        logger.log(f"0x{pos:X}: Wrote decorationCount = {layer['decoration_count']}")

        lastX, lastY, lastPrio = 0.0, 0.0, 0
        for i, deco in enumerate(layer['decorations']):
            d_pos = f.tell()
            dt = deco['type']
            f.write(bytes([dt]))
            if dt == 2:
                write_string(f, deco['string'])
            elif dt == 1:
                f.write(struct.pack('<i', deco['cell']))
            
            currX_int = int(round(deco['position'][0] * 100))
            currY_int = int(round(deco['position'][1] * 100))
            dx = currX_int - int(round(lastX))
            dy = currY_int - int(round(lastY))
            lastX = float(currX_int)
            lastY = float(currY_int)
            
            f.write(struct.pack('<ii', dx, dy))
            f.write(struct.pack('<i', deco['size']['raw']))
            
            ef = deco['extra_flag']
            f.write(bytes([ef]))
            if ef != 0:
                f.write(bytes(deco['extra_bools']))
                f.write(struct.pack('<iiii', *deco['extra_ints']))
                f.write(struct.pack('<i', deco['size_override']['raw']))
                f.write(struct.pack('<h', deco['extra_unknown']))
            
            f.write(bytes(deco['color_rgba']))
            f.write(struct.pack('<ii', deco['dimensions']['raw'][0], deco['dimensions']['raw'][1]))
            
            p_delta = deco['priority']['total'] - lastPrio
            f.write(struct.pack('<i', p_delta))
            lastPrio = deco['priority']['total']
            
            logger.log(f"  0x{d_pos:X}: Wrote Deco {i} type={deco['type']} dx={dx}, dy={dy} p_delta={p_delta}")

duration = time.time() - start_time
logger.log(f"Finished rebuilding binary: {output_bin}")
logger.log(f"Total time: {duration:.4f} seconds ({duration * 1000:.2f} ms)")
logger.close()
