import struct
import json
import sys
from pathlib import Path
from datetime import datetime

# --- LOGGING SETUP ---
class Logger:
    def __init__(self, log_path=None):
        self.log_file = None
        if log_path:
            self.log_file = open(log_path, 'w', encoding='utf-8')
    
    def log(self, message):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        full_message = f"{timestamp} {message}"
        # For verbose scripts, we typically log to file only to keep console clean
        if self.log_file:
            self.log_file.write(full_message + '\n')
            self.log_file.flush()

    def close(self):
        if self.log_file:
            self.log_file.close()

class BinaryReader:
    def __init__(self, data, logger):
        self.data = data
        self.offset = 0
        self.logger = logger

    def read(self, n, desc=""):
        pos = self.offset
        result = self.data[self.offset:self.offset+n]
        self.offset += n
        if desc:
            self.logger.log(f"0x{pos:X}: read {n} bytes ({desc}) -> {result.hex()}")
        return result

    def unpack(self, fmt, desc=""):
        pos = self.offset
        size = struct.calcsize(fmt)
        result = struct.unpack(fmt, self.read(size))
        if desc:
            self.logger.log(f"0x{pos:X}: unpack '{fmt}' ({desc}) -> {result}")
        return result

    def read_int(self, desc=""):
        return self.unpack('<i', desc)[0]

    def read_uint8(self, desc=""):
        return self.unpack('<B', desc)[0]

    def read_short(self, desc=""):
        return self.unpack('<h', desc)[0]

    def read_double(self, desc=""):
        return self.unpack('<d', desc)[0]

    def read_string(self, desc=""):
        pos = self.offset
        length = self.read_int(f"{desc} length")
        if length == 0:
            return None
        s_bytes = self.read(length)
        val = s_bytes.decode('ascii').rstrip('\x00')
        self.logger.log(f"0x{pos:X}: string ({desc}) -> '{val}'")
        return val

def read_level(file_path, logger):
    with open(file_path, 'rb') as f:
        reader = BinaryReader(f.read(), logger)

    level = {}
    level['dummy'] = reader.read_int("header dummy")
    tile_type_count = reader.read_int("tileTypeCount")
    level['tileTypeCount'] = tile_type_count

    tile_types = []
    for i in range(tile_type_count):
        tile_types.append({'value': reader.read_string(f"tileType[{i}]")})
    level['tileTypes'] = tile_types

    layer_count = reader.read_int("layerCount")
    level['layerCount'] = layer_count
    level['layers'] = []

    for layer_idx in range(layer_count):
        logger.log(f"--- START LAYER {layer_idx + 1} ---")
        layer = {}
        
        # 1. Walls
        wall_count = reader.read_int(f"Layer {layer_idx+1} wallCount")
        layer['walls'] = []
        for i in range(wall_count):
            wall = {
                'pos_x': reader.read_double(f"Wall[{i}] pos_x"),
                'pos_y': reader.read_double(f"Wall[{i}] pos_y"),
                'width': reader.read_double(f"Wall[{i}] width"),
                'length': reader.read_double(f"Wall[{i}] length"),
                'wall_type_name': reader.read_string(f"Wall[{i}] type"),
                'has_shapes_flag': reader.read_uint8(f"Wall[{i}] has_shapes_flag")
            }
            if wall['has_shapes_flag'] == 0:
                shape_count = reader.read_int(f"Wall[{i}] shapeCount")
                wall['shapes'] = []
                for j in range(shape_count):
                    shape_type = reader.read_string(f"Wall[{i}] Shape[{j}] type")
                    shape = {'shape_type_name': shape_type}
                    if shape_type == "Circle":
                        shape['data'] = {
                            'center_x': reader.read_double(f"Wall[{i}] Shape[{j}] cx"),
                            'center_y': reader.read_double(f"Wall[{i}] Shape[{j}] cy"),
                            'radius': reader.read_double(f"Wall[{i}] Shape[{j}] r")
                        }
                    else: # ConPoly
                        v_count = reader.read_int(f"Wall[{i}] Shape[{j}] vCount")
                        shape['data'] = {'vertices': [list(reader.unpack('<dd', f"Wall[{i}] Shape[{j}] Vert[{k}]")) for k in range(v_count)]}
                    wall['shapes'].append(shape)
            
            wall['reserved'] = reader.read_int(f"Wall[{i}] reserved")
            wall['wall_id'] = reader.read_int(f"Wall[{i}] wall_id")
            layer['walls'].append(wall)

        # 2. Paths
        path_count = reader.read_int(f"Layer {layer_idx+1} pathCount")
        layer['paths'] = []
        for i in range(path_count):
            path = {
                'path_name': reader.read_string(f"Path[{i}] name"),
                'position': list(reader.unpack('<dd', f"Path[{i}] pos")),
                'extent_x_guess': reader.read_double(f"Path[{i}] extent_x"),
                'extent_y_guess': reader.read_double(f"Path[{i}] extent_y"),
                'path_flag': reader.read_uint8(f"Path[{i}] flag")
            }
            if path['path_flag'] == 1:
                pt_count = reader.read_int(f"Path[{i}] splinePointCount")
                path['spline_points'] = []
                for j in range(pt_count):
                    v = reader.unpack('<dddddd', f"Path[{i}] Spline[{j}]")
                    path['spline_points'].append({
                        'p0': [v[0], v[1]], 'p1': [v[2], v[3]], 'p2': [v[4], v[5]]
                    })
            path['internal_id_guess'] = reader.read_int(f"Path[{i}] internal_id")
            layer['paths'].append(path)

        # 3. Entities
        ent_count = reader.read_int(f"Layer {layer_idx+1} entCount")
        layer['entities'] = []
        last_x, last_y, last_prio = 0, 0, 0
        for i in range(ent_count):
            ent = {'type': reader.read_string(f"Entity[{i}] type")}
            dx, dy = reader.unpack('<ii', f"Entity[{i}] deltaPos")
            last_x += dx
            last_y += dy
            ent['position'] = [last_x * 0.01, last_y * 0.01]
            
            ent['field_158'] = reader.read_int(f"Entity[{i}] field158")
            ent['field_15c'] = reader.read_int(f"Entity[{i}] field15c")
            
            vec = reader.unpack('<ii', f"Entity[{i}] vec")
            ent['vec'] = {'raw': list(vec)}
            
            ent['field_250'] = {'raw': reader.read_int(f"Entity[{i}] field250")}
            ent['rotation'] = {'raw': reader.read_int(f"Entity[{i}] rotation")}
            
            ent['has_box'] = reader.read_uint8(f"Entity[{i}] has_box")
            if ent['has_box'] != 0:
                ent['box'] = {
                    'enabled': reader.read_int(f"Entity[{i}] box_enabled"),
                    'bounds': list(reader.unpack('<iiii', f"Entity[{i}] box_bounds"))
                }
            
            ent['color'] = {'rgba': list(reader.read(4, f"Entity[{i}] color"))}
            ent['mass'] = reader.read_double(f"Entity[{i}] mass")
            
            prio_delta = reader.read_int(f"Entity[{i}] prio_delta")
            last_prio += prio_delta
            ent['priority'] = last_prio
            
            ent['has_move_direction'] = reader.read_int(f"Entity[{i}] has_move")
            if ent['has_move_direction'] == 1:
                v = reader.unpack('<ddidddddd', f"Entity[{i}] move_data")
                ent['move_direction'] = {
                    'v0': v[0], 'v1': v[1], 'flag0': v[2],
                    'v2': v[3], 'v3': v[4], 'v4': v[5], 'v5': v[6], 'v6': v[7], 'v7': v[8]
                }
            
            ent['has_path_follow'] = reader.read_int(f"Entity[{i}] has_path")
            if ent['has_path_follow'] == 1:
                v0, v1 = reader.unpack('<dd', f"Entity[{i}] path_v01")
                f0 = reader.read_int(f"Entity[{i}] path_f0")
                v2, v3 = reader.unpack('<dd', f"Entity[{i}] path_v23")
                ent['path_follow'] = {
                    'v0': v0, 'v1': v1, 'flag0': f0, 'v2': v2, 'v3': v3,
                    'path_name': reader.read_string(f"Entity[{i}] path_name"),
                    'flag1': reader.read_int(f"Entity[{i}] path_f1"),
                    'mode': reader.read_int(f"Entity[{i}] path_mode"),
                    'v4': reader.read_double(f"Entity[{i}] path_v4")
                }

            ent['has_emitter'] = reader.read_int(f"Entity[{i}] has_emitter")
            if ent['has_emitter'] == 1:
                v = reader.unpack('<ddddddddddd', f"Entity[{i}] emitter_data")
                ent['emitter'] = {f'v{i}': v[i] for i in range(11)}
                if layer_idx >= 3:
                    ent['emitter']['reserved'] = reader.read_int(f"Entity[{i}] emitter_reserved")
                    ent['emitter']['end_marker'] = reader.read_int(f"Entity[{i}] emitter_end")
            
            layer['entities'].append(ent)

        # 4. Decorations
        deco_count = reader.read_int(f"Layer {layer_idx+1} decoCount")
        layer['decorations'] = []
        last_x, last_y, last_prio = 0, 0, 0
        for i in range(deco_count):
            deco = {'type': reader.read_uint8(f"Deco[{i}] type")}
            if deco['type'] == 0x02:
                deco['string'] = reader.read_string(f"Deco[{i}] string")
            elif deco['type'] == 0x01:
                deco['cell'] = reader.read_int(f"Deco[{i}] cell")
            
            dx, dy = reader.unpack('<ii', f"Deco[{i}] deltaPos")
            last_x += dx
            last_y += dy
            deco['position'] = [last_x * 0.01, last_y * 0.01]
            
            deco['size'] = {'raw': reader.read_int(f"Deco[{i}] size")}
            deco['extra_flag'] = reader.read_uint8(f"Deco[{i}] extra_flag")
            
            if deco['extra_flag'] != 0:
                deco['extra_bools'] = list(reader.read(2, f"Deco[{i}] extraBools"))
                deco['extra_ints'] = list(reader.unpack('<iiii', f"Deco[{i}] extraInts"))
                deco['size_override'] = {'raw': reader.read_int(f"Deco[{i}] size_override")}
                deco['extra_unknown'] = reader.read_short(f"Deco[{i}] extraUnknown")
            
            deco['color_rgba'] = list(reader.read(4, f"Deco[{i}] color"))
            deco['dimensions'] = {'raw': list(reader.unpack('<ii', f"Deco[{i}] dims"))}
            
            prio_delta = reader.read_int(f"Deco[{i}] prio_delta")
            last_prio += prio_delta
            deco['priority'] = {'total': last_prio}
            layer['decorations'].append(deco)

        level['layers'].append(layer)
    
    return level

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python read_level_verbose.py <level.bin>")
        sys.exit(1)
    
    input_bin = Path(sys.argv[1])
    level_name = input_bin.stem
    output_json = level_name + "_data.json"
    log_file = level_name + "_read_verbose.log"
    
    logger = Logger(log_file)
    logger.log(f"Starting verbose read of {input_bin.name}")
    
    try:
        data = read_level(input_bin, logger)
        with open(output_json, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Successfully converted {input_bin.name} to {output_json}")
        print(f"Verbose log written to {log_file}")
    finally:
        logger.close()
