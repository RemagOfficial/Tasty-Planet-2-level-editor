import struct
import json
import sys
from pathlib import Path

# This script reads a binary level file and converts it to a readable JSON format.
# It is designed to be simple and educational.

class BinaryReader:
    """Helper class to read binary data sequentially."""
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def read(self, n):
        """Read n bytes."""
        result = self.data[self.offset:self.offset+n]
        self.offset += n
        return result

    def unpack(self, fmt):
        """Unpack binary data according to a format string."""
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))

    def read_int(self):
        """Read a 4-byte little-endian signed integer."""
        return self.unpack('<i')[0]

    def read_uint8(self):
        """Read a single byte unsigned integer."""
        return self.unpack('<B')[0]

    def read_short(self):
        """Read a 2-byte little-endian signed short."""
        return self.unpack('<h')[0]

    def read_double(self):
        """Read an 8-byte little-endian double-precision float."""
        return self.unpack('<d')[0]

    def read_string(self):
        """Read a string: 4-byte length followed by bytes (ascii, null-terminated)."""
        length = self.read_int()
        if length == 0:
            return None
        # Read the bytes and decode, removing the null terminator if present.
        return self.read(length).decode('ascii').rstrip('\x00')

def read_level(file_path):
    """Parses the biological level binary format."""
    with open(file_path, 'rb') as f:
        reader = BinaryReader(f.read())

    level = {}
    level['dummy'] = reader.read_int()
    tile_type_count = reader.read_int()
    level['tileTypeCount'] = tile_type_count

    # 1. Tile types (strings)
    tile_types = []
    for _ in range(tile_type_count):
        tile_types.append({'value': reader.read_string()})
    level['tileTypes'] = tile_types

    layer_count = reader.read_int()
    level['layerCount'] = layer_count
    level['layers'] = []

    for layer_idx in range(layer_count):
        layer = {}
        
        # A. Walls
        wall_count = reader.read_int()
        layer['walls'] = []
        for _ in range(wall_count):
            wall = {
                'pos_x': reader.read_double(),
                'pos_y': reader.read_double(),
                'width': reader.read_double(),
                'length': reader.read_double(),
                'wall_type_name': reader.read_string(),
                'has_shapes_flag': reader.read_uint8()
            }
            if wall['has_shapes_flag'] == 0:
                shape_count = reader.read_int()
                wall['shapes'] = []
                for _ in range(shape_count):
                    shape_type = reader.read_string()
                    shape = {'shape_type_name': shape_type}
                    if shape_type == "Circle":
                        shape['data'] = {
                            'center_x': reader.read_double(),
                            'center_y': reader.read_double(),
                            'radius': reader.read_double()
                        }
                    else: # ConPoly (Convex Polygon)
                        v_count = reader.read_int()
                        shape['data'] = {'vertices': [list(reader.unpack('<dd')) for _ in range(v_count)]}
                    wall['shapes'].append(shape)
            
            wall['reserved'] = reader.read_int()
            wall['wall_id'] = reader.read_int()
            layer['walls'].append(wall)

        # B. Paths
        path_count = reader.read_int()
        layer['paths'] = []
        for _ in range(path_count):
            path = {
                'path_name': reader.read_string(),
                'position': list(reader.unpack('<dd')),
                'extent_x_guess': reader.read_double(),
                'extent_y_guess': reader.read_double(),
                'path_flag': reader.read_uint8()
            }
            if path['path_flag'] == 1:
                pt_count = reader.read_int()
                path['spline_points'] = []
                for _ in range(pt_count):
                    v = reader.unpack('<dddddd')
                    path['spline_points'].append({
                        'p0': [v[0], v[1]], 'p1': [v[2], v[3]], 'p2': [v[4], v[5]]
                    })
            path['internal_id_guess'] = reader.read_int()
            layer['paths'].append(path)

        # C. Entities
        ent_count = reader.read_int()
        layer['entities'] = []
        # Entities use accumulated delta positions
        last_x, last_y, last_prio = 0, 0, 0
        for _ in range(ent_count):
            ent = {'type': reader.read_string()}
            dx, dy = reader.unpack('<ii')
            last_x += dx
            last_y += dy
            ent['position'] = [last_x * 0.01, last_y * 0.01]
            
            ent['field_158'] = reader.read_int()
            ent['field_15c'] = reader.read_int()
            
            vec = reader.unpack('<ii')
            ent['vec'] = {'raw': list(vec)}
            
            ent['field_250'] = {'raw': reader.read_int()}
            ent['rotation'] = {'raw': reader.read_int()}
            
            ent['has_box'] = reader.read_uint8()
            if ent['has_box'] != 0:
                ent['box'] = {
                    'enabled': reader.read_int(),
                    'bounds': list(reader.unpack('<iiii'))
                }
            
            ent['color'] = {'rgba': list(reader.read(4))}
            ent['mass'] = reader.read_double()
            
            # Entities use accumulated delta priority
            prio_delta = reader.read_int()
            last_prio += prio_delta
            ent['priority'] = last_prio
            
            ent['has_move_direction'] = reader.read_int()
            if ent['has_move_direction'] == 1:
                v0, v1 = reader.unpack('<dd')
                f0 = reader.read_int()
                v2, v3, v4, v5, v6, v7 = reader.unpack('<dddddd')
                ent['move_direction'] = {
                    'v0': v0, 'v1': v1, 'flag0': f0,
                    'v2': v2, 'v3': v3, 'v4': v4, 'v5': v5, 'v6': v6, 'v7': v7
                }
            
            ent['has_path_follow'] = reader.read_int()
            if ent['has_path_follow'] == 1:
                v0, v1 = reader.unpack('<dd')
                f0 = reader.read_int()
                v2, v3 = reader.unpack('<dd')
                ent['path_follow'] = {
                    'v0': v0, 'v1': v1, 'flag0': f0, 'v2': v2, 'v3': v3,
                    'path_name': reader.read_string(),
                    'flag1': reader.read_int(),
                    'mode': reader.read_int(),
                    'v4': reader.read_double()
                }

            ent['has_emitter'] = reader.read_int()
            if ent['has_emitter'] == 1:
                v = reader.unpack('<ddddddddddd')
                ent['emitter'] = {f'v{i}': v[i] for i in range(11)}
                # Only higher layers have these emitter trailers
                if layer_idx >= 3:
                    ent['emitter']['reserved'] = reader.read_int()
                    ent['emitter']['end_marker'] = reader.read_int()
            
            layer['entities'].append(ent)

        # D. Decorations
        deco_count = reader.read_int()
        layer['decorations'] = []
        last_x, last_y, last_prio = 0, 0, 0
        for _ in range(deco_count):
            deco = {'type': reader.read_uint8()}
            if deco['type'] == 0x02:
                deco['string'] = reader.read_string()
            elif deco['type'] == 0x01:
                deco['cell'] = reader.read_int()
            
            # Decorations use accumulated delta positions
            dx, dy = reader.unpack('<ii')
            last_x += dx
            last_y += dy
            deco['position'] = [last_x * 0.01, last_y * 0.01]
            
            deco['size'] = {'raw': reader.read_int()}
            deco['extra_flag'] = reader.read_uint8()
            
            if deco['extra_flag'] != 0:
                deco['extra_bools'] = list(reader.read(2))
                deco['extra_ints'] = list(reader.unpack('<iiii'))
                deco['size_override'] = {'raw': reader.read_int()}
                deco['extra_unknown'] = reader.read_short()
            
            deco['color_rgba'] = list(reader.read(4))
            deco['dimensions'] = {'raw': list(reader.unpack('<ii'))}
            
            # Decorations use accumulated delta priority
            prio_delta = reader.read_int()
            last_prio += prio_delta
            deco['priority'] = {'total': last_prio}
            layer['decorations'].append(deco)

        level['layers'].append(layer)
    
    return level

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python read_level.py <level.bin>")
        sys.exit(1)
    
    input_bin = sys.argv[1]
    output_json = Path(input_bin).stem + "_data.json"
    
    level_data = read_level(input_bin)
    
    with open(output_json, 'w') as f:
        json.dump(level_data, f, indent=2)
        
    print(f"Successfully converted {input_bin} to {output_json}")
