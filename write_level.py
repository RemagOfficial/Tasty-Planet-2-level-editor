import struct
import json
import sys
from pathlib import Path

# This script reads a JSON level data file and converts it back to binary.
# It ensures byte-for-byte consistency when re-integrating levels.

def pack_string(s):
    """Packs a string: 4-byte length followed by bytes (ascii, null-terminated)."""
    if s is None:
        return struct.pack('<i', 0)
    encoded = s.encode('ascii') + b'\x00'
    return struct.pack('<i', len(encoded)) + encoded

def write_level(data, output_path):
    """Encodes JSON data into the level binary format."""
    with open(output_path, 'wb') as f:
        # Header
        f.write(struct.pack('<i', data.get('dummy', 0)))
        f.write(struct.pack('<i', data.get('tileTypeCount', 0)))

        # 1. Tile Types
        for tile in data.get('tileTypes', []):
            f.write(pack_string(tile.get('value', '')))

        # Layers
        layer_count = data.get('layerCount', 0)
        f.write(struct.pack('<i', layer_count))

        for layer_idx, layer in enumerate(data.get('layers', [])):
            # A. Walls
            walls = layer.get('walls', [])
            f.write(struct.pack('<i', len(walls)))
            for wall in walls:
                f.write(struct.pack('<dddd', 
                    wall.get('pos_x', 0.0), wall.get('pos_y', 0.0), 
                    wall.get('width', 0.0), wall.get('length', 0.0)
                ))
                f.write(pack_string(wall.get('wall_type_name', '')))
                
                has_shapes = wall.get('has_shapes_flag', 1)
                f.write(struct.pack('<B', has_shapes))
                
                if has_shapes == 0:
                    shapes = wall.get('shapes', [])
                    f.write(struct.pack('<i', len(shapes)))
                    for shape in shapes:
                        shape_type = shape.get('shape_type_name', '')
                        f.write(pack_string(shape_type))
                        shape_data = shape.get('data', {})
                        if shape_type == "Circle":
                            f.write(struct.pack('<ddd', 
                                shape_data.get('center_x', 0.0), 
                                shape_data.get('center_y', 0.0), 
                                shape_data.get('radius', 0.0)
                            ))
                        else: # ConPoly
                            vertices = shape_data.get('vertices', [])
                            f.write(struct.pack('<i', len(vertices)))
                            for vx, vy in vertices:
                                f.write(struct.pack('<dd', vx, vy))
                
                f.write(struct.pack('<i', wall.get('reserved', 0)))
                f.write(struct.pack('<i', wall.get('wall_id', 0)))

            # B. Paths
            paths = layer.get('paths', [])
            f.write(struct.pack('<i', len(paths)))
            for path in paths:
                f.write(pack_string(path.get('path_name', '')))
                pos = path.get('position', [0.0, 0.0])
                f.write(struct.pack('<dd', pos[0], pos[1]))
                f.write(struct.pack('<dd', 
                    path.get('extent_x_guess', 0.0), 
                    path.get('extent_y_guess', 0.0)
                ))
                p_flag = path.get('path_flag', 0)
                f.write(struct.pack('<B', p_flag))
                
                if p_flag == 1:
                    points = path.get('spline_points', [])
                    f.write(struct.pack('<i', len(points)))
                    for pt in points:
                        p0, p1, p2 = pt.get('p0', [0,0]), pt.get('p1', [0,0]), pt.get('p2', [0,0])
                        f.write(struct.pack('<dddddd', p0[0], p0[1], p1[0], p1[1], p2[0], p2[1]))
                
                f.write(struct.pack('<i', path.get('internal_id_guess', 0)))

            # C. Entities
            entities = layer.get('entities', [])
            f.write(struct.pack('<i', len(entities)))
            last_x, last_y, last_prio = 0, 0, 0
            
            for ent in entities:
                f.write(pack_string(ent.get('type', '')))
                
                # Delta position encoding
                pos = ent.get('position', [0.0, 0.0])
                curr_x_raw = int(round(pos[0] * 100))
                curr_y_raw = int(round(pos[1] * 100))
                dx, dy = curr_x_raw - last_x, curr_y_raw - last_y
                f.write(struct.pack('<ii', dx, dy))
                last_x, last_y = curr_x_raw, curr_y_raw
                
                f.write(struct.pack('<ii', ent.get('field_158', 0), ent.get('field_15c', 0)))
                
                vec_raw = ent.get('vec', {}).get('raw', [0, 0])
                f.write(struct.pack('<ii', vec_raw[0], vec_raw[1]))
                
                f.write(struct.pack('<ii', 
                    ent.get('field_250', {}).get('raw', 0), 
                    ent.get('rotation', {}).get('raw', 0)
                ))
                
                has_box = ent.get('has_box', 0)
                f.write(struct.pack('<B', has_box))
                if has_box != 0:
                    box = ent.get('box', {})
                    f.write(struct.pack('<i', box.get('enabled', 0)))
                    bounds = box.get('bounds', [0, 0, 0, 0])
                    f.write(struct.pack('<iiii', *bounds))
                
                color = ent.get('color', {}).get('rgba', [255, 255, 255, 255])
                f.write(struct.pack('BBBB', *color))
                f.write(struct.pack('<d', ent.get('mass', 1.0)))
                
                # Delta priority encoding
                curr_prio = ent.get('priority', 0)
                f.write(struct.pack('<i', curr_prio - last_prio))
                last_prio = curr_prio
                
                has_move = ent.get('has_move_direction', 0)
                f.write(struct.pack('<i', has_move))
                if has_move == 1:
                    mv = ent.get('move_direction', {})
                    f.write(struct.pack('<dd', mv.get('v0', 0.0), mv.get('v1', 0.0)))
                    f.write(struct.pack('<i', mv.get('flag0', 0)))
                    f.write(struct.pack('<dddddd', 
                        mv.get('v2', 0.0), mv.get('v3', 0.0), mv.get('v4', 0.0),
                        mv.get('v5', 0.0), mv.get('v6', 0.0), mv.get('v7', 0.0)
                    ))
                
                has_path = ent.get('has_path_follow', 0)
                f.write(struct.pack('<i', has_path))
                if has_path == 1:
                    pf = ent.get('path_follow', {})
                    f.write(struct.pack('<dd', pf.get('v0', 0.0), pf.get('v1', 0.0)))
                    f.write(struct.pack('<i', pf.get('flag0', 0)))
                    f.write(struct.pack('<dd', pf.get('v2', 0.0), pf.get('v3', 0.0)))
                    f.write(pack_string(pf.get('path_name', '')))
                    f.write(struct.pack('<ii', pf.get('flag1', 0), pf.get('mode', 0)))
                    f.write(struct.pack('<d', pf.get('v4', 0.0)))

                has_emitter = ent.get('has_emitter', 0)
                f.write(struct.pack('<i', has_emitter))
                if has_emitter == 1:
                    em = ent.get('emitter', {})
                    f.write(struct.pack('<ddddddddddd', *[em.get(f'v{i}', 0.0) for i in range(11)]))
                    if layer_idx >= 3:
                        f.write(struct.pack('<ii', em.get('reserved', 0), em.get('end_marker', 0)))

            # D. Decorations
            decorations = layer.get('decorations', [])
            f.write(struct.pack('<i', len(decorations)))
            last_x, last_y, last_prio = 0, 0, 0
            
            for deco in decorations:
                deco_type = deco.get('type', 0)
                f.write(struct.pack('<B', deco_type))
                if deco_type == 0x02:
                    f.write(pack_string(deco.get('string', '')))
                elif deco_type == 0x01:
                    f.write(struct.pack('<i', deco.get('cell', 0)))
                
                pos = deco.get('position', [0.0, 0.0])
                curr_x_raw = int(round(pos[0] * 100))
                curr_y_raw = int(round(pos[1] * 100))
                f.write(struct.pack('<ii', curr_x_raw - last_x, curr_y_raw - last_y))
                last_x, last_y = curr_x_raw, curr_y_raw
                
                f.write(struct.pack('<i', deco.get('size', {}).get('raw', 0)))
                extra_flag = deco.get('extra_flag', 0)
                f.write(struct.pack('<B', extra_flag))
                
                if extra_flag != 0:
                    f.write(struct.pack('<BB', *deco.get('extra_bools', [0, 0])))
                    f.write(struct.pack('<iiii', *deco.get('extra_ints', [0,0,0,0])))
                    f.write(struct.pack('<i', deco.get('size_override', {}).get('raw', 0)))
                    f.write(struct.pack('<h', deco.get('extra_unknown', 0)))
                
                f.write(struct.pack('BBBB', *deco.get('color_rgba', [255, 255, 255, 255])))
                dims = deco.get('dimensions', {}).get('raw', [0, 0])
                f.write(struct.pack('<ii', dims[0], dims[1]))
                
                curr_prio = deco.get('priority', {}).get('total', 0)
                f.write(struct.pack('<i', curr_prio - last_prio))
                last_prio = curr_prio

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python write_level.py <level_data.json> [output.bin]")
        sys.exit(1)
        
    input_json = sys.argv[1]
    output_bin = sys.argv[2] if len(sys.argv) > 2 else Path(input_json).with_suffix('.bin_rebuilt')
        
    with open(input_json, 'r') as f:
        data = json.load(f)
        
    write_level(data, output_bin)
    print(f"Successfully rebuilt {input_json} to {output_bin}")
