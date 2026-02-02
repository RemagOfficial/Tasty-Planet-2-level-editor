import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
import os
import sys
import json
import math
import time
import shutil
import re
import zipfile
import copy
import traceback
from PIL import Image, ImageTk
from editor.parser import TPParser
from editor.asset_manager import AssetManager

class EntityManagerDialog(tk.Toplevel):
    def __init__(self, parent, level_editor):
        super().__init__(parent)
        self.title("Manage Entities")
        self.geometry("800x600")
        self.level_editor = level_editor
        self.parser = level_editor.parser
        self.assets = level_editor.assets
        
        self.setup_ui()

    def setup_ui(self):
        toolbar = tk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        tk.Label(toolbar, text="Search:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_list())
        tk.Entry(toolbar, textvariable=self.search_var).pack(side=tk.LEFT, padx=5)

        # Main List
        self.tree = ttk.Treeview(self, columns=("map", "texture"), show="headings")
        self.tree.heading("map", text="Imagemap")
        self.tree.heading("texture", text="Texture Source")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        btn_frame = tk.Frame(self)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=10)
        
        tk.Button(btn_frame, text="Edit Entity", command=self.edit_entity, bg="#007bff", fg="white", width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Delete Entity", command=self.delete_entity, bg="#dc3545", fg="white", width=15).pack(side=tk.LEFT, padx=20)
        tk.Button(btn_frame, text="Close", command=self.destroy, width=15).pack(side=tk.RIGHT, padx=5)
        
        self.refresh_list()

    def refresh_list(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
            
        search_query = self.search_var.get().lower()
        
        # Sort entities by name
        sorted_names = sorted(self.parser.entitydefs.keys())
        
        for name in sorted_names:
            if search_query and search_query not in name.lower():
                continue
                
            e = self.parser.entitydefs[name]
            map_name = e.get('imagemap', '')
            imap = self.parser.imagemaps.get(map_name, {})
            filename = imap.get('filename', '')
            
            self.tree.insert("", "end", iid=name, values=(map_name, filename), text=name)

    def edit_entity(self):
        sel = self.tree.selection()
        if not sel: return
        name = sel[0]
        ent = self.parser.entitydefs[name]
        map_name = ent.get('imagemap')
        imap = self.parser.imagemaps.get(map_name, {})
        
        # Determine actual texture path on disk using central asset manager
        tex_rel_path = imap.get('filename', '')
        tex_path = self.assets.image_files.get(tex_rel_path) or self.assets.image_files.get(tex_rel_path.lower())
        
        if not tex_path:
            # Try stripping extension
            name_strip = os.path.splitext(tex_rel_path)[0].lower().replace("\\", "/")
            tex_path = self.assets.image_files.get(name_strip)

        # Get cell info if any
        cell_info = None
        if ent.get('cell'):
             cell_info = imap.get('cells', {}).get(ent['cell'])

        edit_data = {
            'name': name,
            'imagemap': map_name,
            'cell_info': cell_info,
            'aspectratio': ent.get('aspectratio'),
            'areacoverage': ent.get('areacoverage'),
            'intersections': ent.get('intersections'),
            'tex_path': tex_path
        }
        
        # Close this and open creator in edit mode
        EntityCreatorDialog(self.master, self.level_editor.assets_path, 
                             self.level_editor.assets.graphics_path, 
                             self.level_editor.on_entity_created,
                             self.level_editor.parser,
                             edit_data=edit_data)
        self.destroy()

    def delete_entity(self):
        sel = self.tree.selection()
        if not sel: return
        name = sel[0]
        
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete entity '{name}'? This will remove it from entitydefs.xml."):
            return
            
        try:
            # 1. Remove from entitydefs.xml
            ent_path = os.path.join(self.level_editor.assets.graphics_path, "entitydefs.xml")
            if not os.path.exists(ent_path):
                # Fallback to assets root if graphics/ is just a hint
                ent_path = os.path.join(self.level_editor.assets_path, "entitydefs.xml")
            
            # Create backup before modification
            self.level_editor.parser.create_backup(ent_path)

            with open(ent_path, "r", encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Safe boundary-aware removal
            def remove_ent(text, ent_name):
                # This logic mimics the parser to avoid over-matching malformed Steam XML
                tag_start_pat = rf'<entitydef\s+name="{re.escape(ent_name)}"'
                match = re.search(tag_start_pat, text, re.IGNORECASE)
                if not match: return text
                
                start_ptr = match.start()
                # Find end: either implicit (next <entitydef) or explicit (/> or </entitydef>)
                # Look for explicit first
                explicit_end = -1
                for end_pat in [r'/>', r'</entitydef>']:
                    m_end = re.search(end_pat, text[match.end():], re.IGNORECASE)
                    if m_end:
                        explicit_end = match.end() + m_end.end()
                        break
                
                # Check for implicit boundary (next entity tag)
                next_tag = re.search(r'<entitydef\s+', text[match.end():], re.IGNORECASE)
                if next_tag:
                    implicit_end = match.end() + next_tag.start()
                    # If no explicit end was found, or the explicit end is AFTER the next tag, use implicit
                    if explicit_end == -1 or explicit_end > implicit_end:
                        return text[:start_ptr] + text[implicit_end:]
                
                if explicit_end != -1:
                    return text[:start_ptr] + text[explicit_end:]
                
                # If neither found, it might be the last one
                next_root_end = re.search(r'</entitydefs>', text[match.end():], re.IGNORECASE)
                if next_root_end:
                    root_end_idx = match.end() + next_root_end.start()
                    return text[:start_ptr] + text[root_end_idx:]
                
                return text[:start_ptr] # Last ditch: cut till end
            
            content = remove_ent(content, name)
            
            with open(ent_path, "w", encoding='utf-8') as f:
                f.write(content)
                
            messagebox.showinfo("Deleted", f"Entity '{name}' has been deleted. (Note: Imagemap entries are preserved)")
            self.parser.parse_all()
            self.refresh_list()
            self.level_editor.on_entity_created() # Refresh assets
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete entity: {e}")

class ExportModDialog(tk.Toplevel):
    def __init__(self, parent, current_name):
        super().__init__(parent)
        self.title("Export Mod")
        self.geometry("350x280")
        self.result = None
        self.transient(parent)
        self.grab_set()
        
        tk.Label(self, text="Mod Name:").pack(pady=(15, 0))
        self.ent_name = tk.Entry(self)
        self.ent_name.insert(0, current_name)
        self.ent_name.pack(pady=5)
        
        tk.Label(self, text="Version:").pack()
        self.ent_ver = tk.Entry(self)
        self.ent_ver.insert(0, "1.0.0")
        self.ent_ver.pack(pady=5)
        
        tk.Label(self, text="Author:").pack()
        self.ent_auth = tk.Entry(self)
        self.ent_auth.pack(pady=5)
        
        tk.Button(self, text="Export", command=self.on_export, bg="#28a745", fg="white", width=15).pack(pady=20)
        
    def on_export(self):
        name = self.ent_name.get().strip()
        ver = self.ent_ver.get().strip()
        auth = self.ent_auth.get().strip()
        if not name or not ver:
            messagebox.showerror("Error", "Name and Version are required.")
            return
        self.result = {"name": name, "version": ver, "author": auth}
        self.destroy()

class EntityCreatorDialog(tk.Toplevel):
    def __init__(self, parent, assets_path, graphics_path, callback, parser, edit_data=None):
        super().__init__(parent)
        self.title("Entity Def Creator" if not edit_data else f"Edit Entity: {edit_data['name']}")
        self.geometry("1000x900")
        self.assets_path = assets_path
        self.graphics_path = graphics_path
        self.callback = callback
        self.parser = parser
        self.edit_data = edit_data
        
        self.image_path = ""
        self.pil_img = None
        self.tk_canvas_img = None
        self.selection_rect = None
        self.hitboxes = [] # List of {'type': 'circle'|'rect', 'coords': (x1,y1,x2,y2)}
        self.selection_mode = tk.StringVar(value="texture") # "texture", "circle", "rect"
        
        self.start_x = 0
        self.start_y = 0
        self.current_rect_id = None
        self.scale = 1.0
        
        self.setup_ui()
        if self.edit_data:
            self.load_edit_data()

    def load_edit_data(self):
        d = self.edit_data
        self.ent_name.delete(0, tk.END)
        self.ent_name.insert(0, d['name'])
        self.map_name.delete(0, tk.END)
        self.map_name.insert(0, d['imagemap'])
        self.asp_ratio.delete(0, tk.END)
        self.asp_ratio.insert(0, str(d.get('aspectratio', 1.0)))
        self.area_cov.delete(0, tk.END)
        self.area_cov.insert(0, str(d.get('areacoverage', 0.5)))
        
        # Try to find and load current texture image
        # In edit mode, we might not have the original 'source' image path, 
        # so we load the one currently in the assets.
        tex_path = d.get('tex_path')
        if tex_path and os.path.exists(tex_path):
            self.image_path = tex_path
            self.pil_img = Image.open(tex_path).convert("RGBA")
            self.update_canvas()
            
            # If there's a cell, set the selection rect
            if d.get('cell_info'):
                try:
                    c = d['cell_info']
                    self.selection_rect = (int(c['x1']), int(c['y1']), int(c['x2']), int(c['y2']))
                except: pass
            
            # Hitboxes
            # Need to convert from game-space relative to center back to image-space coords
            # This is tricky because we need the center
            if self.selection_rect:
                cx = (self.selection_rect[0] + self.selection_rect[2]) / 2
                cy = (self.selection_rect[1] + self.selection_rect[3]) / 2
            else:
                cx, cy = self.pil_img.width / 2, self.pil_img.height / 2

            for inter in d.get('intersections', []):
                try:
                    itype = inter['type']
                    a = inter['attr']
                    img_w = self.pil_img.width
                    img_h = self.pil_img.height
                    
                    # Normalize support: Steam uses posx/posy (normalized), 
                    # Legacy used x/y (pixels)
                    px = float(a.get('posx', a.get('x', 0)))
                    py = float(a.get('posy', a.get('y', 0)))

                    if itype == 'circle':
                        r = float(a.get('radius', 0))
                        if 'posx' in a: # Steam normalized
                            hx = (px * img_w) + cx
                            hy = cy - (py * img_h)
                            hr = r * img_h
                        else: # Legacy pixels
                            hx = px + cx
                            hy = cy - py
                            hr = r
                            
                        self.hitboxes.append({
                            'type': 'circle',
                            'coords': (int(hx - hr), int(hy - hr), int(hx + hr), int(hy + hr))
                        })
                    else:
                        if 'posx' in a: # Steam normalized (rotrect style)
                            w = float(a.get('width', 0))
                            h = float(a.get('height', 0))
                            hcx = (px * img_w) + cx
                            hcy = cy - (py * img_h)
                            hw = w * img_w
                            hh = h * img_h
                            hx1, hy1 = hcx - hw/2, hcy - hh/2
                            hx2, hy2 = hcx + hw/2, hcy + hh/2
                        else: # Legacy x1/y1 pixels
                            rx1 = float(a.get('x1', 0))
                            ry1 = float(a.get('y1', 0))
                            rx2 = float(a.get('x2', 0))
                            ry2 = float(a.get('y2', 0))
                            hx1 = rx1 + cx
                            hy1 = cy - ry2
                            hx2 = rx2 + cx
                            hy2 = cy - ry1
                        
                        self.hitboxes.append({
                            'type': 'rect',
                            'coords': (int(hx1), int(hy1), int(hx2), int(hy2))
                        })
                except: pass
            
            self.update_hitbox_list()
            self.update_canvas()

    def setup_ui(self):
        toolbar = tk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        tk.Button(toolbar, text="Step 1: Select Image", command=self.select_image).pack(side=tk.LEFT, padx=5)
        
        mode_frame = tk.LabelFrame(toolbar, text="Selection Mode")
        mode_frame.pack(side=tk.LEFT, padx=20)
        tk.Radiobutton(mode_frame, text="Texture Area", variable=self.selection_mode, value="texture").pack(side=tk.LEFT)
        tk.Radiobutton(mode_frame, text="Add Circle Hitbox", variable=self.selection_mode, value="circle").pack(side=tk.LEFT)
        tk.Radiobutton(mode_frame, text="Add Rect Hitbox", variable=self.selection_mode, value="rect").pack(side=tk.LEFT)

        tk.Button(toolbar, text="Clear Texture Selection", command=self.clear_selection).pack(side=tk.LEFT, padx=5)
        tk.Button(toolbar, text="Clear All Hitboxes", command=self.clear_hitboxes).pack(side=tk.LEFT, padx=5)

        # Main Area
        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Left: Canvas
        canvas_container = tk.Frame(main_frame, bg="gray30")
        canvas_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Scrollbars for canvas
        h_sb = tk.Scrollbar(canvas_container, orient=tk.HORIZONTAL)
        h_sb.pack(side=tk.BOTTOM, fill=tk.X)
        v_sb = tk.Scrollbar(canvas_container, orient=tk.VERTICAL)
        v_sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.canvas = tk.Canvas(canvas_container, bg="gray20", cursor="cross",
                                xscrollcommand=h_sb.set, yscrollcommand=v_sb.set)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        h_sb.config(command=self.canvas.xview)
        v_sb.config(command=self.canvas.yview)
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        # Right: Props
        prop_frame = tk.Frame(main_frame, width=300)
        prop_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        tk.Label(prop_frame, text="Entity Properties", font=("Arial", 12, "bold")).pack(pady=10)
        
        # Fields
        self.ent_name = self.add_field(prop_frame, "Entity Name:", "new_entity_1")
        self.map_name = self.add_field(prop_frame, "Imagemap Name:", "")
        self.asp_ratio = self.add_field(prop_frame, "Aspect Ratio:", "1.0")
        self.area_cov = self.add_field(prop_frame, "Area Coverage:", "0.5")

        tk.Label(prop_frame, text="Hitboxes", font=("Arial", 10, "bold")).pack(pady=(15, 5), anchor="w")
        self.hitbox_list = tk.Listbox(prop_frame, height=6)
        self.hitbox_list.pack(fill=tk.X)
        tk.Button(prop_frame, text="Remove Selected Hitbox", command=self.remove_hitbox).pack(fill=tk.X, pady=2)

        tk.Label(prop_frame, text="Texture Destination", font=("Arial", 10, "bold")).pack(pady=(15, 5), anchor="w")
        
        # Subfolder path
        self.sub_path = self.add_field(prop_frame, "Subfolder (e.g. EA/Entities):", "")
        
        # Mode selection
        self.dest_mode = tk.StringVar(value="both")
        mode_frame = tk.Frame(prop_frame)
        mode_frame.pack(fill=tk.X, pady=5)
        tk.Radiobutton(mode_frame, text="Both", variable=self.dest_mode, value="both").pack(side=tk.LEFT)
        tk.Radiobutton(mode_frame, text="New Only", variable=self.dest_mode, value="new").pack(side=tk.LEFT)
        tk.Radiobutton(mode_frame, text="Old Only", variable=self.dest_mode, value="old").pack(side=tk.LEFT)
        
        tk.Button(prop_frame, text="Step 3: Save Entity", command=self.save_entity, 
                  bg="#28a745", fg="white", font=("Arial", 10, "bold"), height=2).pack(side=tk.BOTTOM, fill=tk.X, pady=20)

    def add_field(self, parent, label, default):
        f = tk.Frame(parent)
        f.pack(fill=tk.X, pady=5)
        tk.Label(f, text=label).pack(anchor="w")
        e = tk.Entry(f)
        e.insert(0, default)
        e.pack(fill=tk.X)
        return e

    def select_image(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            self.image_path = path
            self.pil_img = Image.open(path).convert("RGBA")
            self.update_canvas()
            
            # Default map name to filename
            if not self.map_name.get():
                name = os.path.splitext(os.path.basename(path))[0]
                self.map_name.delete(0, tk.END)
                self.map_name.insert(0, name)

    def update_canvas(self):
        if not self.pil_img: return
        self.canvas.delete("all")
        
        iw, ih = self.pil_img.size
        self.tk_canvas_img = ImageTk.PhotoImage(self.pil_img)
        self.canvas.create_image(0, 0, image=self.tk_canvas_img, anchor="nw")
        
        # Draw selections
        if self.selection_rect:
            x1, y1, x2, y2 = self.selection_rect
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2, dash=(4,4))
            
        for hb in self.hitboxes:
            x1, y1, x2, y2 = hb['coords']
            if hb['type'] == "rect":
                self.canvas.create_rectangle(x1, y1, x2, y2, outline="green", width=2)
            else:
                self.canvas.create_oval(x1, y1, x2, y2, outline="cyan", width=2)

        self.canvas.config(scrollregion=(0, 0, iw, ih))

    def on_press(self, event):
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        if self.current_rect_id:
            self.canvas.delete(self.current_rect_id)
        
        mode = self.selection_mode.get()
        if mode == "texture" or mode == "rect":
            self.current_rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, 
                                                              outline="red" if mode == "texture" else "green", width=2)
        elif mode == "circle":
            self.current_rect_id = self.canvas.create_oval(self.start_x, self.start_y, self.start_x, self.start_y, 
                                                          outline="cyan", width=2)

    def on_drag(self, event):
        if not self.current_rect_id: return
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.current_rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        if not self.current_rect_id: return
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        
        # Standardize coords
        x1, y1 = int(min(self.start_x, cur_x)), int(min(self.start_y, cur_y))
        x2, y2 = int(max(self.start_x, cur_x)), int(max(self.start_y, cur_y))
        
        mode = self.selection_mode.get()
        if mode == "texture":
            self.selection_rect = (x1, y1, x2, y2)
        else:
            self.hitboxes.append({'type': mode, 'coords': (x1, y1, x2, y2)})
            self.update_hitbox_list()
        
        self.current_rect_id = None
        self.update_canvas()

    def clear_selection(self):
        self.selection_rect = None
        self.update_canvas()

    def clear_hitboxes(self):
        self.hitboxes = []
        self.update_hitbox_list()
        self.update_canvas()

    def update_hitbox_list(self):
        self.hitbox_list.delete(0, tk.END)
        for i, hb in enumerate(self.hitboxes):
            self.hitbox_list.insert(tk.END, f"{i}: {hb['type']} {hb['coords']}")

    def remove_hitbox(self):
        sel = self.hitbox_list.curselection()
        if sel:
            idx = sel[0]
            del self.hitboxes[idx]
            self.update_hitbox_list()
            self.update_canvas()

    def save_entity(self):
        if not self.image_path or not self.ent_name.get():
            messagebox.showerror("Error", "Missing Image or Entity Name")
            return
            
        try:
            # 1. Determine destination base folders
            dest_folders = []
            mode = self.dest_mode.get()
            if mode == "both" or mode == "new":
                new_path = os.path.join(self.graphics_path, "newgraphics")
                if os.path.exists(new_path): dest_folders.append(new_path)
            if mode == "both" or mode == "old":
                old_path = os.path.join(self.graphics_path, "oldgraphics")
                if os.path.exists(old_path): dest_folders.append(old_path)
            
            # Fallback if no specific graphics folders found
            if not dest_folders:
                dest_folders = [self.graphics_path]

            sub = self.sub_path.get().strip().replace("\\", "/")
            if sub.startswith("/"): sub = sub[1:]
            
            base_filename = os.path.splitext(os.path.basename(self.image_path))[0]
            extension = os.path.splitext(self.image_path)[1]
            
            # This is what goes into filename="" in imagemaps.xml
            xml_filename = f"{sub}/{base_filename}" if sub else base_filename
            
            # Copy file to all selected destinations
            for base in dest_folders:
                target_dir = os.path.join(base, sub) if sub else base
                os.makedirs(target_dir, exist_ok=True)
                target_file = os.path.join(target_dir, base_filename + extension)
                if os.path.abspath(self.image_path) != os.path.abspath(target_file):
                    shutil.copy2(self.image_path, target_file)
            
            # 2. Add to Imagemaps.xml
            imap_path = os.path.join(self.graphics_path, "imagemaps.xml")
            self.parser.create_backup(imap_path)
            map_name = self.map_name.get()
            
            with open(imap_path, "r", encoding='utf-8', errors='ignore') as f:
                imap_content = f.read()
            
            # Check if map exists
            if f'name="{map_name}"' not in imap_content:
                new_map_xml = f'\n\n\t<!-- Modded Entities -->\n\t<imagemap name="{map_name}" filename="{xml_filename}" alwaysneeded="true" width="{self.pil_img.width}" height="{self.pil_img.height}">\n'
                if self.selection_rect:
                    x1, y1, x2, y2 = self.selection_rect
                    new_map_xml += f'\t\t<cell name="{self.ent_name.get()}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" />\n'
                else:
                    new_map_xml += '\t\t<fullimagecell />\n'
                new_map_xml += '\t</imagemap>\n'
                
                imap_content = imap_content.replace('</imagemaps>', new_map_xml + '</imagemaps>')
            else:
                # Add cell to existing map
                if self.selection_rect:
                    x1, y1, x2, y2 = self.selection_rect
                    cell_xml = f'\t\t<cell name="{self.ent_name.get()}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" />\n'
                    # Find the closing tag for this imagemap
                    pattern = rf'<imagemap\s+name="{map_name}".*?</imagemap>'
                    match = re.search(pattern, imap_content, re.DOTALL)
                    if match:
                        old_block = match.group(0)
                        new_block = old_block.replace('</imagemap>', cell_xml + '\t</imagemap>')
                        imap_content = imap_content.replace(old_block, new_block)

            with open(imap_path, "w", encoding='utf-8') as f:
                f.write(imap_content)

            # Calculate Center for Hitboxes (Entity Origin)
            if self.selection_rect:
                sx1, sy1, sx2, sy2 = self.selection_rect
                center_x = (sx1 + sx2) / 2
                center_y = (sy1 + sy2) / 2
            else:
                center_x = self.pil_img.width / 2
                center_y = self.pil_img.height / 2

            # 3. Add to Entitydefs.xml
            ent_path = os.path.join(self.graphics_path, "entitydefs.xml")
            self.parser.create_backup(ent_path)
            with open(ent_path, "r", encoding='utf-8', errors='ignore') as f:
                ent_content = f.read()
                
            # Construct Intersection XML (Steam Style: intersectionshapes, posx/posy, normalized)
            intersections_block = ""
            if self.hitboxes:
                intersections_block = "\n\t\t<intersectionshapes>"
                img_w = self.pil_img.width
                img_h = self.pil_img.height
                
                for hb in self.hitboxes:
                    hx1, hy1, hx2, hy2 = hb['coords']
                    # Calculate center and dimensions in pixels
                    hcx = (hx1 + hx2) / 2
                    hcy = (hy1 + hy2) / 2
                    hw = hx2 - hx1
                    hh = hy2 - hy1
                    
                    # Normalize (-0.5 to 0.5 for pos, 0.0 to 1.0 for size)
                    # Y is flipped (Steam uses Y-Up)
                    norm_x = round((hcx - center_x) / img_w, 6)
                    norm_y = round((center_y - hcy) / img_h, 6)
                    
                    if hb['type'] == 'circle':
                        radius = (hx2 - hx1) / 2
                        # Circle radius is typically relative to the height (unit) in TP1
                        norm_r = round(radius / img_h, 6)
                        intersections_block += f'\n\t\t\t<circle posx="{norm_x}" posy="{norm_y}" radius="{norm_r}" />'
                    else:
                        norm_w = round(hw / img_w, 6)
                        norm_h = round(hh / img_h, 6)
                        # We use rotrect as it is more flexible/supported by Steam
                        intersections_block += f'\n\t\t\t<rotrect posx="{norm_x}" posy="{norm_y}" width="{norm_w}" height="{norm_h}" angle="0.000000" />'
                intersections_block += "\n\t\t</intersectionshapes>"

            new_ent_xml = f'\n\t<!-- Modded Entities -->\n\t<entitydef name="{self.ent_name.get()}" imagemap="{map_name}"'
            if self.selection_rect:
                new_ent_xml += f' cell="{self.ent_name.get()}"'
            
            if intersections_block:
                new_ent_xml += f' aspectratio="{self.asp_ratio.get()}" areacoverage="{self.area_cov.get()}">{intersections_block}\n\t</entitydef>\n'
            else:
                new_ent_xml += f' aspectratio="{self.asp_ratio.get()}" areacoverage="{self.area_cov.get()}" />\n'

            # If editing, remove old entry first using boundary-safe logic
            if self.edit_data:
                old_name = self.edit_data['name']
                def remove_ent_safe(text, name):
                    tag_pat = rf'<entitydef\s+name="{re.escape(name)}"'
                    m = re.search(tag_pat, text, re.IGNORECASE)
                    if not m: return text
                    
                    # Check for preceding comment
                    start_pos = m.start()
                    pre_text = text[:start_pos]
                    comment_search = re.search(r'<!--.*?-->\s*$', pre_text, re.DOTALL)
                    if comment_search: start_pos = comment_search.start()
                    
                    # Find end
                    explicit_end = -1
                    for end_pat in [r'/>', r'</entitydef>']:
                        m_end = re.search(end_pat, text[m.end():], re.IGNORECASE)
                        if m_end:
                            explicit_end = m.end() + m_end.end()
                            break
                    
                    next_tag = re.search(r'<entitydef\s+', text[m.end():], re.IGNORECASE)
                    if next_tag:
                        implicit_end = m.end() + next_tag.start()
                        if explicit_end == -1 or explicit_end > implicit_end:
                            return text[:start_pos] + text[implicit_end:]
                    
                    if explicit_end != -1:
                        return text[:start_pos] + text[explicit_end:]
                    
                    # Root close is safety
                    next_root = re.search(r'</entitydefs>', text[m.end():], re.IGNORECASE)
                    if next_root: return text[:start_pos] + text[m.end() + next_root.start():]
                    
                    return text[:start_pos]

                ent_content = remove_ent_safe(ent_content, old_name)

            # Ensure </entitydefs> exists, or append it
            if '</entitydefs>' in ent_content.lower():
                ent_content = re.sub(r'</entitydefs>', new_ent_xml + '</entitydefs>', ent_content, flags=re.IGNORECASE, count=1)
            else:
                ent_content += "\n" + new_ent_xml + "\n</entitydefs>"
            
            with open(ent_path, "w", encoding='utf-8') as f:
                f.write(ent_content)
            
            self.callback()
            self.destroy()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save entity: {e}")


class LevelEditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Tasty Planet 1 Level Editor")
        try:
            self.root.geometry("1200x800")
        except:
            pass

        if getattr(sys, 'frozen', False):
            self.app_dir = os.path.dirname(sys.executable)
        else:
            self.app_dir = os.path.dirname(__file__)

        self.config_path = os.path.join(self.app_dir, "config.json")
        self.root_path = ""
        self.assets_path = ""
        self.graphics_mode = "new"
        self.show_text = True
        self.load_config()
        
        self.parser = None
        self.assets = None
        self.current_level_data = None
        self.current_level_name = ""

        # Rendering/View State
        self.zoom = 0.5
        self.offset_x = 400
        self.offset_y = 300
        self.selected_emitter_idx = -1
        self.selected_tile_info = None # (layer_idx, tile_idx)
        self.selected_goo = False
        self.dragging_emitter = False
        self.dragging_goo = False
        self.panning = False
        self.last_mouse_pos = (0, 0)
        self.pupil_center_factor = 1.0 # 0.0 = centered, 1.0 = looking at mouse

        self.visible_layers = {} # layer_idx: bool
        self.show_emitters = True
        self.updating_tree = False
        self.is_swapping = False
        self.start_app_time = time.time()
        self.setup_ui()
        
        # Start animation loop
        self.animate()
        
        # mod selection flow
        self.root.after(100, self.initial_mod_check)

    def initial_mod_check(self):
        if not self.root_path or not os.path.exists(self.root_path):
            self.select_root_folder()
        else:
            # Ensure every folder containing "assets" has a .mod_metadata.json identity
            try:
                for item in os.listdir(self.root_path):
                    full_p = os.path.join(self.root_path, item)
                    if os.path.isdir(full_p) and "assets" in item.lower():
                        meta_path = os.path.join(full_p, ".mod_metadata.json")
                        if not os.path.exists(meta_path):
                            # Infer identity from folder name for migration
                            if item == "assets":
                                self.set_mod_metadata(full_p, "VANILLA")
                            elif item.startswith("assets-"):
                                self.set_mod_metadata(full_p, item[7:])
                            else:
                                self.set_mod_metadata(full_p, item)
            except Exception as e:
                print(f"Metadata auto-repair failed: {e}")
            
            if not self.assets_path or not os.path.exists(self.assets_path):
                self.show_mod_selection()
            else:
                self.load_assets(show_success=False)

    def get_mod_metadata(self, path):
        meta_path = os.path.join(path, ".mod_metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r") as f:
                    return json.load(f).get("name")
            except: pass
        # Infer from folder name if no metadata
        name = os.path.basename(path)
        if name == "assets": return "VANILLA"
        if name.startswith("assets-"): return name[7:]
        return name

    def set_mod_metadata(self, path, name):
        meta_path = os.path.join(path, ".mod_metadata.json")
        # Only create if it doesn't exist, or if we're tagging the base assets folder
        if os.path.exists(meta_path) and name != "VANILLA":
            return
        try:
            with open(meta_path, "w") as f:
                json.dump({"name": name}, f)
        except: pass

    def select_root_folder(self):
        btn = messagebox.askokcancel("Select Game Folder", "Please select the Tasty Planet root folder (the one containing the 'assets' folder).")
        if not btn: return

        path = filedialog.askdirectory(title="Select Tasty Planet Root Folder")
        if path:
            self.root_path = path
            self.save_config()
            self.show_mod_selection()

    def perform_swap(self, target_path, current_assets_path, dialog):
        try:
            # Remember the current level to attempt reload after swap
            level_to_reload = self.current_level_name

            # 0. Get all names/metadata BEFORE we close handles or rename
            curr_name = "UNKNOWN"
            if os.path.exists(current_assets_path):
                curr_name = self.get_mod_metadata(current_assets_path)

            # 1. CRITICAL: Close all resources
            if self.assets:
                self.assets.unload()
            self.assets = None
            self.parser = None
            self.current_level_data = None
            
            # Force current working directory to the game root to ensure we aren't "in" assets
            os.chdir(self.root_path)

            # Force garbage collection
            import gc
            gc.collect()
            time.sleep(0.5) # Give Windows a moment to release handles

            def robust_rename(src, dst):
                """Rename with retries and cleanup for Windows process locking."""
                if not os.path.exists(src): return False
                
                # If target folder exists (and it's not the same as source), 
                # we must move it or rename it first to avoid collision.
                if os.path.exists(dst) and os.path.abspath(src) != os.path.abspath(dst):
                    # Destination folder already exists. This happens if merging or if 
                    # a previous swap failed. We'll rename it to a backup.
                    backup_dst = dst + "-backup-" + str(int(time.time()))
                    try: os.rename(dst, backup_dst)
                    except: pass 

                max_attempts = 8
                for i in range(max_attempts):
                    try:
                        # Use shutil.move as it is sometimes more robust than os.rename
                        shutil.move(src, dst)
                        return True
                    except (PermissionError, OSError) as e:
                        if i == max_attempts - 1:
                            messagebox.showwarning("Access Denied", 
                                f"Windows is blocking the folder swap.\n\n"
                                f"Please CLOSE any Windows Explorer windows at {self.root_path} "
                                f"and ensure no game files are open in other apps, then try again.\n\n{e}")
                            raise
                        print(f"Rename attempt {i+1} failed ({e}), retrying...")
                        time.sleep(0.7)
                return False

            # 2. Rename current 'assets' to its original name
            if os.path.exists(current_assets_path):
                temp_rename = os.path.join(self.root_path, f"assets-{curr_name}")
                if os.path.abspath(temp_rename) != os.path.abspath(current_assets_path):
                    print(f"Swapping OUT: {current_assets_path} -> {temp_rename}")
                    robust_rename(current_assets_path, temp_rename)
            
            # 3. Rename selected target to 'assets'
            print(f"Swapping IN: {target_path} -> {current_assets_path}")
            robust_rename(target_path, current_assets_path)
            self.assets_path = current_assets_path
            
            self.save_config()
            self.load_assets(show_success=False)
            
            # Attempt to reload the level if it exists in the new mod
            if level_to_reload:
                try:
                    self.level_selector.set(level_to_reload)
                    self.load_level()
                except: pass
                
            dialog.destroy()
        except Exception as e:
            err_msg = f"Failed to swap mod folders: {e}\n\n{traceback.format_exc()}"
            print(f"!! SWAP ERROR: {err_msg}")
            messagebox.showerror("Rename Error", err_msg)
        finally:
            self.is_swapping = False
            self.redraw_canvas()

    def show_mod_selection(self):
        if not self.root_path or not os.path.exists(self.root_path):
            self.select_root_folder()
            return

        # Find folders in root_path that contain "assets"
        mod_folders = []
        try:
            for item in os.listdir(self.root_path):
                full_path = os.path.join(self.root_path, item)
                if os.path.isdir(full_path) and "assets" in item.lower():
                    mod_folders.append(item)
        except Exception as e:
            messagebox.showerror("Error", f"Could not scan root folder: {e}")
            return

        # Mod Selection Dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Select or Create Mod")
        dialog.geometry("400x450")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Select an assets folder to edit:", font=("Arial", 10, "bold")).pack(pady=10)
        
        list_frame = tk.Frame(dialog)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        lb = tk.Listbox(list_frame)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(list_frame, command=lb.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb.config(yscrollcommand=sb.set)

        for folder in mod_folders:
            lb.insert(tk.END, folder)
            if folder == os.path.basename(self.assets_path):
                lb.select_set(tk.END)

        def on_select():
            selected = lb.curselection()
            if selected:
                folder_name = lb.get(selected[0])
                target_path = os.path.join(self.root_path, folder_name)
                current_assets_path = os.path.join(self.root_path, "assets")
                
                # Perform swapping if necessary
                if folder_name != "assets":
                    self.is_swapping = True
                    self.current_level_data = None
                    self.canvas.delete("all")
                    # Small delay to ensure any pending draw calls or file reads finish
                    self.root.after(100, lambda: self.perform_swap(target_path, current_assets_path, dialog))
                else:
                    self.assets_path = target_path
                    self.save_config()
                    self.load_assets(show_success=False)
                    dialog.destroy()

        def on_create():
            mod_name = tk.simpledialog.askstring("New Mod", "Enter mod name:", parent=dialog)
            if mod_name:
                mod_name = mod_name.strip().replace(" ", "-")
                if mod_name.upper() == "VANILLA":
                    messagebox.showerror("Error", "Cannot name a mod 'VANILLA'.")
                    return

                new_folder_name = f"assets-{mod_name}"
                new_path = os.path.join(self.root_path, new_folder_name)
                
                # Find vanilla folder as source (the one tagged "VANILLA")
                vanilla_src = None
                for item in os.listdir(self.root_path):
                    full_p = os.path.join(self.root_path, item)
                    if os.path.isdir(full_p) and "assets" in item.lower():
                        if self.get_mod_metadata(full_p) == "VANILLA":
                            vanilla_src = full_p
                            break
                
                if not vanilla_src:
                    # Fallback to current 'assets' if vanilla isn't found/tagged yet
                    vanilla_src = os.path.join(self.root_path, "assets")

                if not os.path.exists(vanilla_src):
                    messagebox.showerror("Error", "Could not locate vanilla assets to clone.")
                    return

                if os.path.exists(new_path):
                    messagebox.showerror("Error", f"Mod folder '{new_folder_name}' already exists.")
                    return

                try:
                    self.is_swapping = True
                    # Unload resources before cloning if we're cloning the active assets
                    if self.assets:
                        self.assets.unload()
                    self.assets = None
                    self.parser = None
                    import gc
                    gc.collect()

                    level_to_reload = self.current_level_name
                    self.current_level_data = None
                    self.canvas.delete("all")
                    
                    print(f"Cloning vanilla assets ({os.path.basename(vanilla_src)}) to {new_path}...")
                    shutil.copytree(vanilla_src, new_path)
                    
                    # Store its identity
                    self.set_mod_metadata(new_path, mod_name)
                    
                    # Now swap it in search of the active 'assets' slot
                    current_assets_path = os.path.join(self.root_path, "assets")
                    if os.path.exists(current_assets_path):
                        curr_name = self.get_mod_metadata(current_assets_path)
                        temp_rename = os.path.join(self.root_path, f"assets-{curr_name}")
                        if os.path.exists(temp_rename) and temp_rename != current_assets_path:
                            temp_rename += f"-{int(time.time())}"
                        os.rename(current_assets_path, temp_rename)
                    
                    # Rename the new clone to 'assets'
                    os.rename(new_path, current_assets_path)
                    
                    self.assets_path = current_assets_path
                    self.save_config()
                    self.load_assets(show_success=True)

                    if level_to_reload:
                        self.level_selector.set(level_to_reload)
                        self.load_level()

                    dialog.destroy()
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to create mod: {e}")
                finally:
                    self.is_swapping = False

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=20)
        
        tk.Button(btn_frame, text="Select Mod", command=on_select, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Create New Mod", command=on_create, width=15).pack(side=tk.LEFT, padx=5)

        def on_export():
            selected = lb.curselection()
            if selected:
                folder_name = lb.get(selected[0])
                self.export_mod(folder_name)
            else:
                messagebox.showwarning("Warning", "Please select a mod to export.")

        def on_import():
            def refresh_list():
                lb.delete(0, tk.END)
                new_folders = []
                for item in os.listdir(self.root_path):
                    if os.path.isdir(os.path.join(self.root_path, item)) and "assets" in item.lower():
                        new_folders.append(item)
                for f in new_folders: lb.insert(tk.END, f)
            self.import_mod(refresh_list)

        btn_frame2 = tk.Frame(dialog)
        btn_frame2.pack(pady=5)
        tk.Button(btn_frame2, text="Export .tpmod", command=on_export, width=15, bg="#6c757d", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame2, text="Import .tpmod", command=on_import, width=15, bg="#0d6efd", fg="white").pack(side=tk.LEFT, padx=5)

    def export_mod(self, folder_name):
        target_path = os.path.join(self.root_path, folder_name)
        mod_identity = self.get_mod_metadata(target_path)
        
        dialog = ExportModDialog(self.root, mod_identity)
        self.root.wait_window(dialog)
        
        if not dialog.result: return
        
        meta = dialog.result
        export_filename = f"{meta['name']}-{meta['version']}.tpmod"
        
        save_path = filedialog.asksaveasfilename(
            defaultextension=".tpmod",
            initialfile=export_filename,
            filetypes=[("Tasty Planet Mod", "*.tpmod")]
        )
        
        if not save_path: return
        
        try:
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add metadata
                zipf.writestr('metadata.json', json.dumps(meta, indent=4))
                
                # Add all files from mod folder
                for root, dirs, files in os.walk(target_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, target_path)
                        # Don't include the internal metadata file if it exists
                        if rel_path == ".mod_metadata.json": continue 
                        zipf.write(file_path, os.path.join('assets', rel_path))
            
            messagebox.showinfo("Export Success", f"Mod exported to {save_path}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export mod: {e}")

    def import_mod(self, list_refresh_callback):
        file_path = filedialog.askopenfilename(
            title="Select .tpmod file",
            filetypes=[("Tasty Planet Mod", "*.tpmod")]
        )
        if not file_path: return
        
        try:
            with zipfile.ZipFile(file_path, 'r') as zipf:
                if 'metadata.json' not in zipf.namelist():
                    messagebox.showerror("Import Error", "Invalid .tpmod file: missing metadata.json")
                    return
                
                meta_content = zipf.read('metadata.json')
                meta = json.loads(meta_content)
                mod_name = meta.get('name', 'imported-mod')
                
                new_folder_name = f"assets-{mod_name}"
                new_path = os.path.join(self.root_path, new_folder_name)
                
                # Handle existing folder
                if os.path.exists(new_path):
                    new_folder_name = f"assets-{mod_name}-{int(time.time())}"
                    new_path = os.path.join(self.root_path, new_folder_name)
                
                # Extract
                os.makedirs(new_path, exist_ok=True)
                for member in zipf.infolist():
                    if member.filename.startswith('assets/'):
                        # Create a copy of the member so we don't modify the original
                        target_member = copy.copy(member)
                        # Strip the leading 'assets/' from the path
                        rel_path = member.filename[len('assets/'):]
                        if not rel_path: continue
                        target_member.filename = rel_path
                        zipf.extract(target_member, new_path)
                
                # Set metadata
                self.set_mod_metadata(new_path, mod_name)
                
                messagebox.showinfo("Import Success", f"Mod '{mod_name}' imported as '{new_folder_name}'")
                list_refresh_callback()
                
        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to import mod: {e}")

    def export_current_mod(self):
        if not self.assets_path: return
        self.export_mod(os.path.basename(self.assets_path))

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                    self.root_path = config.get("root_path", "")
                    self.assets_path = config.get("assets_path", "")
                    self.graphics_mode = config.get("graphics_mode", "new")
                    self.show_text = config.get("show_text", True)
            except:
                pass

    def save_config(self):
        try:
            with open(self.config_path, "w") as f:
                json.dump({
                    "root_path": self.root_path,
                    "assets_path": self.assets_path,
                    "graphics_mode": self.graphics_mode,
                    "show_text": self.show_text
                }, f)
        except:
            pass

    def setup_ui(self):
        # Main Menu
        self.menu_bar = tk.Menu(self.root)
        self.root.config(menu=self.menu_bar)

        # File Menu
        self.file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="Select Game Root Folder", command=self.select_root_folder)
        self.file_menu.add_command(label="Switch/Create Mod", command=self.show_mod_selection)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Export Current Mod", command=self.export_current_mod, state="disabled")
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Save Level", command=self.save_current_level, state="disabled")
        self.file_menu.add_command(label="Revert to Original", command=self.revert_level, state="disabled")
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.root.quit)

        # Edit Menu
        self.edit_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Edit", menu=self.edit_menu)
        self.edit_menu.add_command(label="Add Emitter", command=self.add_emitter, state="disabled")
        self.edit_menu.add_command(label="Delete Selected", command=self.delete_selected, state="disabled")
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Bulk Replace Emitters", command=self.bulk_replace_emitters_dialog, state="disabled")
        self.edit_menu.add_command(label="Bulk Replace Tiles", command=self.bulk_replace_tiles_dialog, state="disabled")
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Create New Entity Def", command=self.open_entity_creator, state="disabled")
        self.edit_menu.add_command(label="Manage Entities", command=self.open_entity_manager, state="disabled")

        # View Menu
        self.view_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="View", menu=self.view_menu)
        self.view_menu.add_command(label="Toggle Emitters", command=self.toggle_emitters)
        self.view_menu.add_command(label="Toggle Text", command=self.toggle_text)
        self.view_menu.add_command(label="Toggle Graphics Mode", command=self.toggle_graphics)

        # Toolbar for Level Selector
        toolbar = tk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Label(toolbar, text="Level:").pack(side=tk.LEFT, padx=5, pady=5)
        self.level_selector = ttk.Combobox(toolbar, state="disabled", width=30)
        self.level_selector.pack(side=tk.LEFT, padx=5, pady=5)
        self.level_selector.bind("<<ComboboxSelected>>", self.load_level)

        # Mode Indicator
        self.mode_label = tk.Label(toolbar, text=f"Graphics: {self.graphics_mode.upper()}", font=("Arial", 10, "bold"), fg="blue")
        self.mode_label.pack(side=tk.RIGHT, padx=10)

        # Main content area
        self.paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # Left side: Properties
        self.prop_frame = tk.Frame(self.paned)
        self.paned.add(self.prop_frame, width=400)

        # Layers Visibility Frame
        self.layers_visibility_frame = tk.LabelFrame(self.prop_frame, text="Layer Visibility")
        self.layers_visibility_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # Create a frame for tree + scrollbar
        tree_container = tk.Frame(self.prop_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_container, columns=("value"), show="tree headings")
        self.tree.heading("#0", text="Property / Item")
        self.tree.heading("value", text="Value")
        self.tree.column("value", width=150)
        
        sb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.tag_configure("selected", background="gray70")
        
        self.tile_items = {} # Mapping of (layer_idx, tile_idx) -> item_id
        self.emitter_items = {} # Mapping of emitter_idx -> item_id
        self.goo_item = None
        self.layer_items = {}
        
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open) # Lazy loading
        self.tree.bind("<Double-1>", self.on_tree_double_click)

        # Center: Level Canvas
        self.canvas_frame = tk.Frame(self.paned)
        self.paned.add(self.canvas_frame, width=880)
        
        self.canvas = tk.Canvas(self.canvas_frame, bg="gray20", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<ButtonPress-1>", self.on_click)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonPress-3>", self.start_pan)
        self.canvas.bind("<B3-Motion>", self.do_pan)
        self.canvas.bind("<ButtonRelease-3>", self.end_pan)

    def select_assets(self):
        # This is now handled by show_mod_selection
        self.show_mod_selection()

    def load_assets(self, show_success=True):
        if not self.assets_path:
            self.show_mod_selection()
            return

        # Double check if assets_path actually exists after rename/swap
        if not os.path.exists(self.assets_path):
            alt_path = os.path.join(self.root_path, "assets")
            if os.path.exists(alt_path):
                self.assets_path = alt_path
            else:
                self.show_mod_selection()
                return

        try:
            # Use metadata to get true name
            true_name = self.get_mod_metadata(self.assets_path)
            self.root.title(f"Tasty Planet 1 Level Editor - [{true_name}]")

            # Reset local state
            self.current_level_data = None
            self.current_level_name = ""
            self.canvas.delete("all")
            self.tree.delete(*self.tree.get_children())

            # CONTEXT: In Tasty Planet, XMLs are consistently in the /graphics folder
            graphics_dir = os.path.join(self.assets_path, "graphics")
            if not os.path.exists(graphics_dir):
                graphics_dir = self.assets_path

            print(f"--- Loading Mod: {true_name} ---")
            print(f"DEBUG: Assets Path: {self.assets_path}")
            print(f"DEBUG: Graphics Path: {graphics_dir}")

            self.parser = TPParser(self.assets_path)
            self.parser.graphics_path = graphics_dir
            self.parser.parse_all()
            
            # Diagnostic for parser issues
            ent_count = len(self.parser.entitydefs)
            print(f"DEBUG: Parser loaded {ent_count} entities.")
            
            if ent_count <= 2:
                messagebox.showerror("CRITICAL WARNING", 
                    f"The editor only found {ent_count} entities in entitydefs.xml.\n\n"
                    f"File being read: {os.path.join(graphics_dir, 'entitydefs.xml')}\n\n"
                    "This usually means the parser is failing to read the Steam version's XML format. "
                    "Mod textures will NOT load correctly.")
            
            self.assets = AssetManager(self.assets_path, self.parser)
            self.assets.graphics_mode = self.graphics_mode
            self.assets.graphics_path = graphics_dir
            self.assets.load_all_graphics()
            
            # Refresh level list - Search ONLY in the selected assets
            level_files = set()
            
            # Assets levels
            assets_levels = os.path.join(self.assets_path, "levels")
            if not os.path.exists(assets_levels):
                assets_levels = self.assets_path
            
            if os.path.exists(assets_levels):
                for f in os.listdir(assets_levels):
                    if f.endswith('.xml') and f != "medaltimes.xml":
                        level_files.add(f)
            
            self.levels_path = assets_levels # Fallback path for saving or metadata
            if level_files:
                self.level_selector['values'] = sorted(list(level_files))
                self.level_selector.config(state="readonly")
                
                # Enable menu items
                self.file_menu.entryconfig("Save Level", state="normal")
                self.file_menu.entryconfig("Export Current Mod", state="normal")
                self.edit_menu.entryconfig("Add Emitter", state="normal")
                self.edit_menu.entryconfig("Delete Selected", state="normal")
                self.edit_menu.entryconfig("Bulk Replace Emitters", state="normal")
                self.edit_menu.entryconfig("Bulk Replace Tiles", state="normal")
                self.edit_menu.entryconfig("Create New Entity Def", state="normal")
                self.edit_menu.entryconfig("Manage Entities", state="normal")

                if show_success:
                    messagebox.showinfo("Success", f"Mod Loaded: {true_name}\n({len(self.assets.images)} images found)")
            
            self.redraw_canvas()
        except Exception as e:
            if show_success:
                messagebox.showerror("Error", f"Failed to load mod: {e}")
            import traceback
            traceback.print_exc()

    def toggle_graphics(self):
        self.graphics_mode = "old" if self.graphics_mode == "new" else "new"
        self.save_config()
        
        if self.assets:
            self.assets.graphics_mode = self.graphics_mode
            self.assets.load_all_graphics()
            if hasattr(self, 'mode_label'):
                self.mode_label.config(text=f"Graphics: {self.graphics_mode.upper()}")
            self.redraw_canvas()

    def open_entity_creator(self):
        if not self.assets_path: return
        # Ensure we have a valid graphics path
        dialog = EntityCreatorDialog(self.root, self.assets_path, self.assets.graphics_path, self.on_entity_created, self.parser)

    def open_entity_manager(self):
        if not self.assets_path: return
        EntityManagerDialog(self.root, self)

    def on_entity_created(self):
        # Refresh everything
        if self.assets:
            self.parser.parse_all()
            self.assets.load_all_graphics()
            messagebox.showinfo("Success", "New entity created and loaded!")

    def toggle_text(self):
        self.show_text = not self.show_text
        self.save_config()
        self.redraw_canvas()

    def toggle_emitters(self):
        self.show_emitters = not self.show_emitters
        self.redraw_canvas()

    def toggle_layer(self, idx):
        self.visible_layers[idx] = not self.visible_layers.get(idx, True)
        self.redraw_canvas()

    def create_outlined_text(self, x, y, text, fill="white", outline="black", tags=None, **kwargs):
        # Draw outline by placing text in 8 directions around the center
        for dx, dy in [(-1,-1), (1,-1), (-1,1), (1,1), (0,-1), (0,1), (-1,0), (1,0)]:
            self.canvas.create_text(x+dx, y+dy, text=text, fill=outline, tags=tags, **kwargs)
        # Main text
        return self.canvas.create_text(x, y, text=text, fill=fill, tags=tags, **kwargs)

    def load_level(self, event=None):
        name = self.level_selector.get()
        if not name: return
        
        # Backup system
        try:
            levels_folder = os.path.join(os.path.dirname(__file__), "levels")
            backups_folder = os.path.join(os.path.dirname(__file__), "backups")
            if not os.path.exists(backups_folder):
                os.makedirs(backups_folder)
            
            src = os.path.join(levels_folder, f"{name}.xml")
            dst = os.path.join(backups_folder, f"{name}.xml")
            
            if os.path.exists(src) and not os.path.exists(dst):
                import shutil
                shutil.copy2(src, dst)
        except Exception as e:
            pass

        self.current_level_data = self.parser.load_level(name)
        self.current_level_name = name
        
        if self.current_level_data:
            self.assets.clear_tk_cache() # Clear cache when loading new level
            self.update_prop_tree()
            self.file_menu.entryconfig("Save Level", state="normal")
            self.file_menu.entryconfig("Revert to Original", state="normal")
            self.edit_menu.entryconfig("Add Emitter", state="normal")
            self.edit_menu.entryconfig("Delete Selected", state="normal")
            self.edit_menu.entryconfig("Bulk Replace Emitters", state="normal")
            self.edit_menu.entryconfig("Bulk Replace Tiles", state="normal")
            self.edit_menu.entryconfig("Create New Entity Def", state="normal")
            self.edit_menu.entryconfig("Manage Entities", state="normal")
            self.redraw_canvas()
        else:
            messagebox.showerror("Error", f"Failed to load level {name}")

    def revert_level(self):
        if not self.current_level_name: return
        
        name = self.current_level_name
        backups_folder = os.path.join(os.path.dirname(__file__), "backups")
        backup_path = os.path.join(backups_folder, f"{name}.xml")
        
        if not os.path.exists(backup_path):
            messagebox.showinfo("No Backup", f"No initial backup found for {name}.xml")
            return
            
        if not messagebox.askyesno("Revert Level", f"Are you sure you want to revert {name}.xml to its original state? All unsaved changes will be lost."):
            return
            
        try:
            levels_folder = os.path.join(os.path.dirname(__file__), "levels")
            target_path = os.path.join(levels_folder, f"{name}.xml")
            
            import shutil
            shutil.copy2(backup_path, target_path)
            
            # Reload the level
            self.current_level_data = self.parser.load_level(name)
            self.assets.clear_tk_cache()
            self.update_prop_tree()
            self.redraw_canvas()
            messagebox.showinfo("Success", f"Reverted {name}.xml to original state.")
        except Exception as e:
            messagebox.showerror("Revert Failed", f"Failed to revert level: {e}")

    def animate(self):
        # Refresh the canvas for animations
        if self.is_swapping:
            self.root.after(100, self.animate)
            return

        try:
            if self.current_level_data:
                self.redraw_canvas()
        except Exception as e:
            # Print to console but don't stop the loop (though we might want to if it's spammy)
            # For now, just catch to avoid crashing the main thread
            print(f"Animation error: {e}")
            
        # ~30 FPS
        self.root.after(33, self.animate)

    def redraw_canvas(self):
        if not self.current_level_data: return
        self.canvas.delete("all")
        
        elapsed = time.time() - self.start_app_time
        props = self.current_level_data.get('properties', {})
        try:
            w = float(props.get('width', 4000))
            h = float(props.get('height', 4000))
            l = float(props.get('left', -w/2))
            r = float(props.get('right', w/2))
            t = float(props.get('top', h/2))
            b = float(props.get('bottom', -h/2))
            
            x1 = l * self.zoom + self.offset_x
            y1 = -t * self.zoom + self.offset_y
            x2 = r * self.zoom + self.offset_x
            y2 = -b * self.zoom + self.offset_y
        except:
            l, r, t, b = -2000, 2000, 2000, -2000
            x1, y1, x2, y2 = 0, 0, 0, 0

        # Preserve bounds for distribution
        draw_bounds = (x1, y1, x2, y2)
        
        # Screen bounds for culling (add some margin)
        canvas_w = self.canvas.winfo_width() or 800
        canvas_h = self.canvas.winfo_height() or 600
        margin = 300 * self.zoom
        
        # Draw Grid/Tiles
        for layer_idx, layer in enumerate(self.current_level_data.get('tilelayers', [])):
            if not self.visible_layers.get(layer_idx, True):
                continue
                
            tw = int(layer.get('tilewidth', 256))
            th = int(layer.get('tileheight', 256))
            cols = int(layer.get('tileswide', 1))
            rows = int(layer.get('tileshigh', 1))
            
            for i, tile_attr in enumerate(layer.get('tiles', [])):
                col = i % cols
                row = i // cols
                
                # World units relative to level left and bottom
                wx = l + (col + 0.5) * tw
                wy = b + (row + 0.5) * th
                
                # Screen units
                dx = wx * self.zoom + self.offset_x
                dy = -wy * self.zoom + self.offset_y
                
                # Culling: skip drawing if far outside screen
                if dx < -margin or dx > canvas_w + margin or dy < -margin or dy > canvas_h + margin:
                    continue

                if isinstance(tile_attr, str):
                    tile_name = tile_attr
                    tile_attr = {'name': tile_name}
                else:
                    tile_name = tile_attr.get('name')

                pil_img = self.assets.get_tile_image(tile_name, elapsed)
                if pil_img:
                    angle = float(tile_attr.get('angle', 0))
                    fx = tile_attr.get('flipx') is True or tile_attr.get('flipx') == 'true'
                    fy = tile_attr.get('flipy') is True or tile_attr.get('flipy') == 'true'
                    alpha = float(tile_attr.get('a', 1.0))
                    tr = float(tile_attr.get('r', 1.0))
                    tg = float(tile_attr.get('g', 1.0))
                    tb = float(tile_attr.get('b', 1.0))
                    
                    tile_scale = (tw / pil_img.width) if pil_img.width > 0 else 1.0
                    tk_img = self.assets.get_tk_image(pil_img, self.zoom * tile_scale, angle, fx, fy, alpha, (tr, tg, tb), transpose_v=True)
                    self.canvas.create_image(dx, dy, image=tk_img, anchor="center", tags=("tile", f"tile_{layer_idx}_{i}"))

        # Draw Selection Highlight
        if self.selected_tile_info:
            layer_idx, i = self.selected_tile_info
            layer = self.current_level_data['tilelayers'][layer_idx]
            tw = int(layer.get('tilewidth', 256))
            th = int(layer.get('tileheight', 256))
            cols = int(layer.get('tileswide', 1))
            col = i % cols
            row = i // cols
            wx = l + (col + 0.5) * tw
            wy = b + (row + 0.5) * th
            dx = wx * self.zoom + self.offset_x
            dy = -wy * self.zoom + self.offset_y
            self.canvas.create_rectangle(dx - (tw*self.zoom)/2, dy - (th*self.zoom)/2,
                                       dx + (tw*self.zoom)/2, dy + (th*self.zoom)/2,
                                       outline="white", width=3, dash=(4,4), tags="tile_selection")

        # Draw Emitters
        if self.show_emitters:
            emitters = self.current_level_data.get('emitters', [])
            side_emitters = [e for e in emitters if e.get('type') == 'side']
            side_count = len(side_emitters)
            
            labels_to_draw = []
            overlays_to_draw = []
            
            for i, emitter in enumerate(emitters):
                if emitter.get('type') == 'shot':
                    continue
                    
                ent_name = emitter.get('entitydef')
                pil_img = self.assets.get_entity_image(ent_name, elapsed)
                
                # Path follow and Move Direction logic
                path_points = []
                move_dir = None
                init_pos = 0.0
                for ctrl in emitter.get('controllers', []):
                    ctype = ctrl.get('type')
                    if ctype == 'pathfollow' and ctrl.get('pairs'):
                        init_pos = float(ctrl.get('initpathpos', 0))
                        for pair in ctrl['pairs']:
                            try:
                                px1 = float(pair.get('x1', 0))
                                py1 = float(pair.get('y1', 0))
                                pcx1 = float(pair.get('coefx1', 0))
                                pcy1 = float(pair.get('coefy1', 0))
                                px2 = float(pair.get('x2', 0))
                                py2 = float(pair.get('y2', 0))
                                pcx2 = float(pair.get('coefx2', 0))
                                pcy2 = float(pair.get('coefy2', 0))
                                path_points.append(((px1, py1), (px1+pcx1, py1+pcy1), (px2+pcx2, py2+pcy2), (px2, py2)))
                            except:
                                continue
                    elif ctype == 'movedirection':
                        try:
                            move_dir = {
                                'angle': float(ctrl.get('direction', 0)),
                                'speed': float(ctrl.get('speed', 0)),
                                'variance': float(ctrl.get('directionvariance', 0))
                            }
                        except:
                            pass

                if emitter.get('type') == 'side':
                    # Distribute on the left side
                    idx_in_side = side_emitters.index(emitter)
                    
                    px = l - 20     # 20 units to the left of level bounds
                    # Evenly distribute between top and bottom bounds
                    if side_count > 1:
                        py = t - ((t - b) / (side_count - 1)) * idx_in_side
                    else:
                        py = (t + b) / 2
                    angle = float(emitter.get('angle', 0))
                elif path_points:
                    # Calculate start position based on initpathpos
                    seg_idx = int(init_pos)
                    seg_t = init_pos - seg_idx
                    if seg_idx >= len(path_points):
                        seg_idx = len(path_points) - 1
                        seg_t = 1.0
                    
                    p0, p1, p2, p3 = path_points[seg_idx]
                    px = (1-seg_t)**3 * p0[0] + 3*(1-seg_t)**2 * seg_t * p1[0] + 3*(1-seg_t) * seg_t**2 * p2[0] + seg_t**3 * p3[0]
                    py = (1-seg_t)**3 * p0[1] + 3*(1-seg_t)**2 * seg_t * p1[1] + 3*(1-seg_t) * seg_t**2 * p2[1] + seg_t**3 * p3[1]
                    angle = float(emitter.get('angle', 0))
                else:
                    px = float(emitter.get('posx', 0))
                    py = float(emitter.get('posy', 0))
                    angle = float(emitter.get('angle', 0))
                
                dx = px * self.zoom + self.offset_x
                dy = -py * self.zoom + self.offset_y
                
                color = "red" if i == self.selected_emitter_idx else ("cyan" if emitter.get('type') == 'side' else "green")
                
                # Store overlays for later (selection required for path/arrow/cone)
                if i == self.selected_emitter_idx:
                    overlays_to_draw.append({
                        'dx': dx, 'dy': dy, 
                        'path': path_points, 
                        'move_dir': move_dir, 
                        'color': color
                    })

                ent_def = self.parser.entitydefs.get(ent_name, {})
                areacoverage = ent_def.get('areacoverage', 1.0)
                
                # Calculate physical scale based on area
                min_area = float(emitter.get('minarea', 0))
                max_area = float(emitter.get('maxarea', 0))
                
                # If areas are 0, use a default scale (1.0)
                # Otherwise, use the square root formula: Scale = sqrt(Area / (BaseArea * coverage))
                physics_scale = 1.0
                max_physics_scale = 1.0
                
                if pil_img and min_area > 0:
                    base_area = pil_img.width * pil_img.height * areacoverage
                    physics_scale = (min_area / base_area)**0.5 if base_area > 0 else 1.0
                    if max_area > 0:
                        max_physics_scale = (max_area / base_area)**0.5 if base_area > 0 else physics_scale
                    else:
                        max_physics_scale = physics_scale

                if pil_img:
                    # Use physics_scale * self.zoom as the final scale for the texture
                    tk_img = self.assets.get_tk_image(pil_img, self.zoom * physics_scale, angle)
                    self.canvas.create_image(dx, dy, image=tk_img, anchor="center", tags=("emitter", f"e_{i}"))
                    
                    # Draw Selection Highlight for Emitter
                    if i == self.selected_emitter_idx:
                        ew = pil_img.width * physics_scale * self.zoom
                        eh = pil_img.height * physics_scale * self.zoom
                        self.canvas.create_rectangle(dx - ew/2, dy - eh/2, dx + ew/2, dy + eh/2,
                                                   outline="white", width=2, dash=(4,4), tags="emitter_selection")

                    # Draw a dashed circle for maxarea if it's different
                    if max_area > min_area and emitter.get('type') == 'spot':
                        max_w = pil_img.width * max_physics_scale * self.zoom
                        max_h = pil_img.height * max_physics_scale * self.zoom
                        self.canvas.create_oval(dx - max_w/2, dy - max_h/2, dx + max_w/2, dy + max_h/2, 
                                              outline=color, dash=(2, 2), tags=("emitter_range", f"e_{i}"))
                    
                    label_y = dy + (pil_img.height * physics_scale * self.zoom / 2) + 10
                else:
                    self.canvas.create_oval(dx-5, dy-5, dx+5, dy+5, fill=color, tags=("emitter_dot", f"e_{i}"))
                    if i == self.selected_emitter_idx:
                        self.canvas.create_oval(dx-8, dy-8, dx+8, dy+8, outline="white", width=2, dash=(2,2), tags="emitter_selection")
                    label_y = dy + 15
                
                labels_to_draw.append((dx, label_y, f"{ent_name} ({emitter.get('type', 'spot')})"))

            # Draw Overlays (Paths and Move Arrows) Above Textures
            for overlay in overlays_to_draw:
                dx, dy = overlay['dx'], overlay['dy']
                path = overlay['path']
                move_dir = overlay['move_dir']
                
                if path:
                    for p0, p1, p2, p3 in path:
                        steps = 20
                        prev_pt = None
                        for t_idx in range(steps + 1):
                            step_t = t_idx / steps
                            bx = (1-step_t)**3 * p0[0] + 3*(1-step_t)**2 * step_t * p1[0] + 3*(1-step_t) * step_t**2 * p2[0] + step_t**3 * p3[0]
                            by = (1-step_t)**3 * p0[1] + 3*(1-step_t)**2 * step_t * p1[1] + 3*(1-step_t) * step_t**2 * p2[1] + step_t**3 * p3[1]
                            bdx = bx * self.zoom + self.offset_x
                            bdy = -by * self.zoom + self.offset_y
                            if prev_pt:
                                self.canvas.create_line(prev_pt[0], prev_pt[1], bdx, bdy, fill="white", dash=(2, 2), tags="emitter_overlay")
                            prev_pt = (bdx, bdy)

                if move_dir:
                    length = max(30, move_dir['speed'] * 0.5) * self.zoom
                    rad = math.radians(move_dir['angle'])
                    adx = dx + math.cos(rad) * length
                    ady = dy - math.sin(rad) * length
                    self.canvas.create_line(dx, dy, adx, ady, fill="yellow", arrow=tk.LAST, width=2, tags="emitter_overlay")
                    
                    if move_dir['variance'] > 0:
                        v_rad_1 = math.radians(move_dir['angle'] + move_dir['variance'])
                        v_rad_2 = math.radians(move_dir['angle'] - move_dir['variance'])
                        vdx1 = dx + math.cos(v_rad_1) * length * 0.8
                        vdy1 = dy - math.sin(v_rad_1) * length * 0.8
                        vdx2 = dx + math.cos(v_rad_2) * length * 0.8
                        vdy2 = dy - math.sin(v_rad_2) * length * 0.8
                        self.canvas.create_line(dx, dy, vdx1, vdy1, fill="yellow", dash=(4, 4), tags="emitter_overlay")
                        self.canvas.create_line(dx, dy, vdx2, vdy2, fill="yellow", dash=(4, 4), tags="emitter_overlay")

            # Draw Bounds Last (so they are on top)
            if 'draw_bounds' in locals() and any(draw_bounds):
                bx1, by1, bx2, by2 = draw_bounds
                self.canvas.create_rectangle(bx1, by1, bx2, by2, outline="yellow", dash=(5, 5), width=2, tags="bounds")
                if self.show_text:
                    self.create_outlined_text(bx1, by1 - 10, text="Level Bounds", fill="yellow", anchor="sw", tags="bounds_text")

            # Draw Emitter Labels Over Everything
            if self.show_text:
                drawn_positions = []
                for dx, dy, text in labels_to_draw:
                    # Simple overlap prevention: shift down if too close to another label
                    for px, py in drawn_positions:
                        if abs(dx - px) < 100 and abs(dy - py) < 20:
                            dy += 20
                    self.create_outlined_text(dx, dy, text=text, fill="white", tags="emitter_text")
                    drawn_positions.append((dx, dy))
        else:
            # Still draw bounds if emitters are hidden
            if 'draw_bounds' in locals() and any(draw_bounds):
                bx1, by1, bx2, by2 = draw_bounds
                self.canvas.create_rectangle(bx1, by1, bx2, by2, outline="yellow", dash=(5, 5), width=2, tags="bounds")
                if self.show_text:
                    self.create_outlined_text(bx1, by1 - 10, text="Level Bounds", fill="yellow", anchor="sw", tags="bounds_text")

        # Draw Goo Spawn (Always on top of emitters)
        goo = self.current_level_data.get('goo')
        if goo:
            gx = float(goo.get('x', 0))
            gy = float(goo.get('y', 0))
            area = float(goo.get('area', 0))
            gdx = gx * self.zoom + self.offset_x
            gdy = -gy * self.zoom + self.offset_y
            
            # Determine correct animations based on graphics mode
            # Both "goo" and "eyeblink" will automatically switch to "new..." versions in new mode via AssetManager
            base_anim = "goo"
            eye_anim = "eyeblink" if self.assets.graphics_mode == "old" else "eyelid"
            
            # Use 'greygoo' definition for physical scaling properties
            ent_def = self.parser.entitydefs.get("greygoo", {})
            areacoverage = ent_def.get('areacoverage', 0.49)
            
            # 1. Draw Base Goo
            pil_img = self.assets.get_animation_frame(base_anim, elapsed)
            if not pil_img:
                # Fallback to general greygoo/goo if specialized anim not found
                pil_img = self.assets.get_entity_image("greygoo", elapsed) or self.assets.get_entity_image("goo", elapsed)

            physics_scale = 1.0
            if pil_img:
                # Calculate scale. We apply a 4.0x "editor boost" to make the tiny starting goo visible
                base_area = pil_img.width * pil_img.height * areacoverage
                physics_scale = ((area / base_area)**0.5 if base_area > 0 and area > 0 else 1.0) * 4.0
                tk_img = self.assets.get_tk_image(pil_img, self.zoom * physics_scale)
                self.canvas.create_image(gdx, gdy, image=tk_img, anchor="center", tags="goo")

                # Eye scale multiplier (user requested larger eyes)
                eye_scale_mult = 1.25
                eye_phys_scale = physics_scale * eye_scale_mult

                # Pupil specific boost for new graphics (requested by user)
                pupil_phys_scale = eye_phys_scale * (1.6 if self.assets.graphics_mode == "new" else 1.0)

                # 2. Draw Eyes (TWO, offset) - actual eye texture, between body and eyelid
                if self.assets.graphics_mode == "new":
                    # newgoo0 sheet, cell 'gooeyes'
                    eye_img = self.assets.get_cell_by_id("newgoo0", cell_name="gooeyes")
                else:
                    # Old graphics: use the 'eyeball' imagemap (full image or first cell)
                    eye_img = self.assets.get_cell_by_id("eyeball")
                if self.assets.graphics_mode == "new":
                    eye_offset_x = pil_img.width * self.zoom * physics_scale * 0.18
                    eye_offset_y = pil_img.height * self.zoom * physics_scale * 0.18
                else:
                    eye_offset_x = pil_img.width * self.zoom * physics_scale * 0.14
                    eye_offset_y = 0
                if eye_img:
                    eye_tk = self.assets.get_tk_image(eye_img, self.zoom * eye_phys_scale)
                    self.canvas.create_image(gdx - eye_offset_x, gdy + eye_offset_y, image=eye_tk, anchor="center", tags="goo")
                    self.canvas.create_image(gdx + eye_offset_x, gdy + eye_offset_y, image=eye_tk, anchor="center", tags="goo")

                # 2.1 Draw pupils (above eyeballs, under eyelids)
                # Get mouse position in SCREEN pixels
                mouse_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
                mouse_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
                
                # Check if mouse is over the Goo body
                dist_to_goo = ((mouse_x - gdx)**2 + (mouse_y - gdy)**2)**0.5
                goo_radius = (pil_img.width / 2) * self.zoom * physics_scale if pil_img else 0
                is_over_goo = dist_to_goo < (goo_radius * 1.1) # 10% buffer

                # Smoothly transition the "centeredness" factor (0.0 = center, 1.0 = at mouse)
                target_factor = 0.0 if is_over_goo else 1.0
                self.pupil_center_factor += (target_factor - self.pupil_center_factor) * 0.28 # Faster smooth transition

                for sign in [-1, 1]:
                    # cx, cy are the screen coordinates of the eye center
                    cx = gdx + sign * eye_offset_x
                    cy = gdy + eye_offset_y
                    
                    # Target offset from eye center in screen pixels
                    dx = (mouse_x - cx) * self.pupil_center_factor
                    dy = (mouse_y - cy) * self.pupil_center_factor
                    
                    if self.assets.graphics_mode == "new":
                        pupil_img = self.assets.get_cell_by_id("newgoo0", cell_name="goopupils")
                        curr_eye_img = self.assets.get_cell_by_id("newgoo0", cell_name="gooeyes")
                    else:
                        pupil_img = self.assets.get_cell_by_id(None, cell_name="pupil")
                        curr_eye_img = self.assets.get_cell_by_id(None, cell_name="eyeball")
                    
                    if curr_eye_img:
                        # Radius in screen pixels
                        # Eyeball stays at normal eye_phys_scale
                        eye_radius = (curr_eye_img.width / 2) * self.zoom * eye_phys_scale
                        # Pupil uses its own scale
                        pupil_width = pupil_img.width if pupil_img else 0
                        pupil_radius = (pupil_width / 2) * self.zoom * pupil_phys_scale
                        
                        # Max displacement from center in screen pixels
                        max_d = eye_radius - pupil_radius - 2 * self.zoom
                        max_d = max(0, max_d)
                        
                        dist = (dx**2 + dy**2)**0.5
                        if dist > max_d:
                            scale = max_d / dist
                            dx *= scale
                            dy *= scale
                    
                    if pupil_img:
                        # Draw pupil with the larger pupil_phys_scale
                        pupil_tk = self.assets.get_tk_image(pupil_img, self.zoom * pupil_phys_scale)
                        self.canvas.create_image(cx + dx, cy + dy, image=pupil_tk, anchor="center", tags="goo")

                # 2.5 Draw eyelid animation (TWO, offset, above eyes and pupils)
                # Only draw if the blink animation is currently active (within its duration)
                eye_elapsed = elapsed % 4.0
                anim_def = self.assets.parser.animationdefs.get(eye_anim)
                anim_duration = anim_def.get('time', 0.25) if anim_def else 0.25
                
                if eye_elapsed < anim_duration:
                    eye_pil = self.assets.get_animation_frame(eye_anim, eye_elapsed)
                    if eye_pil:
                        eye_tk = self.assets.get_tk_image(eye_pil, self.zoom * eye_phys_scale)
                        self.canvas.create_image(gdx - eye_offset_x, gdy + eye_offset_y, image=eye_tk, anchor="center", tags="goo")
                        self.canvas.create_image(gdx + eye_offset_x, gdy + eye_offset_y, image=eye_tk, anchor="center", tags="goo")
                
            else:
                print(f"DEBUG: Failed to find any texture for Goo Body. Mode: {self.graphics_mode}")
                # Fallback shapes if zero textures found (e.g. if new graphics fail to load)
                # Use a red circle to make it clear that a texture is missing
                r = self.zoom * 20 
                self.canvas.create_oval(gdx-r, gdy-r, gdx+r, gdy+r, fill="#ff0000", outline="white", width=2, tags="goo")
                self.canvas.create_line(gdx-r*1.5, gdy, gdx+r*1.5, gdy, fill="white", tags="goo")
                self.canvas.create_line(gdx, gdy-r*1.5, gdx, gdy+r*1.5, fill="white", tags="goo")
            
            if self.selected_goo:
                if pil_img:
                    gw, gh = pil_img.width * self.zoom * physics_scale, pil_img.height * self.zoom * physics_scale
                    self.canvas.create_rectangle(gdx - gw/2, gdy - gh/2, gdx + gw/2, gdy + gh/2,
                                               outline="white", width=2, dash=(4,4), tags="goo_selection")
                else:
                    self.canvas.create_oval(gdx-12, gdy-12, gdx+12, gdy+12, outline="white", width=2, dash=(4,4), tags="goo_selection")

            if self.show_text:
                self.create_outlined_text(gdx, gdy-20, text="Goo Spawn", fill="yellow", tags="goo_text")

        # Screen info
        if self.show_text:
            self.create_outlined_text(10, 10, text=f"Zoom: {self.zoom:.2f} | Right-click drag to pan | Left-click drag to move emitters", anchor="nw", fill="white")

    def on_mouse_wheel(self, event):
        if event.delta > 0:
            self.zoom *= 1.1
        else:
            self.zoom /= 1.1
        self.zoom = max(0.01, min(10.0, self.zoom))
        self.redraw_canvas()

    def start_pan(self, event):
        self.panning = True
        self.last_mouse_pos = (event.x, event.y)

    def do_pan(self, event):
        if self.panning:
            dx = event.x - self.last_mouse_pos[0]
            dy = event.y - self.last_mouse_pos[1]
            self.offset_x += dx
            self.offset_y += dy
            self.last_mouse_pos = (event.x, event.y)
            self.redraw_canvas()

    def end_pan(self, event):
        self.panning = False

    def on_click(self, event):
        # Convert screen to world
        world_x = (event.x - self.offset_x) / self.zoom
        world_y = -(event.y - self.offset_y) / self.zoom
        
        # Selection
        self.selected_emitter_idx = -1
        self.selected_tile_info = None
        self.selected_goo = False
        
        emitters = self.current_level_data.get('emitters', [])
        side_emitters = [e for e in emitters if e.get('type') == 'side']
        side_count = len(side_emitters)
        props = self.current_level_data.get('properties', {})
        
        # Calculate level bounds correctly
        try:
            w = float(props.get('width', 4000))
            h = float(props.get('height', 4000))
            l = float(props.get('left', -w/2))
            r = float(props.get('right', w/2))
            t = float(props.get('top', h/2))
            b = float(props.get('bottom', -h/2))
        except:
            l, r, t, b = -2000, 2000, 2000, -2000

        # 0. Check Goo (Highest priority)
        goo = self.current_level_data.get('goo')
        if goo:
            gx = float(goo.get('x', 0))
            gy = float(goo.get('y', 0))
            dist = ((world_x - gx)**2 + (world_y - gy)**2)**0.5
            if dist < 30 / self.zoom:
                self.selected_goo = True
                self.dragging_goo = True
                self.redraw_canvas()
                self.sync_tree_selection()
                return

        # 1. Check Emitters (Medium priority)
        hit_emitter = False
        if self.show_emitters:
            for i, emitter in enumerate(emitters):
                if emitter.get('type') == 'side':
                    idx_in_side = side_emitters.index(emitter)
                    ex = l - 20 # Match redraw_canvas
                    if side_count > 1:
                        ey = t - ((t - b) / (side_count - 1)) * idx_in_side
                    else:
                        ey = (t + b) / 2
                else:
                    ex = float(emitter.get('posx', 0))
                    ey = float(emitter.get('posy', 0))

                dist = ((world_x - ex)**2 + (world_y - ey)**2)**0.5
                if dist < 30 / self.zoom:
                    self.selected_emitter_idx = i
                    if emitter.get('type') != 'side':
                        self.dragging_emitter = True
                    hit_emitter = True
                    break
        
        # 2. Check Tiles (Lower priority)
        if not hit_emitter:
            layers = self.current_level_data.get('tilelayers', [])
            # Check layers top-to-bottom
            for layer_idx in reversed(range(len(layers))):
                if not self.visible_layers.get(layer_idx, True):
                    continue
                    
                layer = layers[layer_idx]
                tw = int(layer.get('tilewidth', 256))
                th = int(layer.get('tileheight', 256))
                cols = int(layer.get('tileswide', 1))
                rows = int(layer.get('tileshigh', 1))
                
                # Check if click is within this layer's grid
                lx = l
                by = b
                rx = l + cols * tw
                ty = b + rows * th
                
                if lx <= world_x <= rx and by <= world_y <= ty:
                    col = int((world_x - lx) // tw)
                    row = int((world_y - by) // th)
                    if 0 <= col < cols and 0 <= row < rows:
                        tile_idx = row * cols + col
                        if tile_idx < len(layer.get('tiles', [])):
                            self.selected_tile_info = (layer_idx, tile_idx)
                            break
        
        self.redraw_canvas()
        self.sync_tree_selection()

    def on_drag(self, event):
        world_x = (event.x - self.offset_x) / self.zoom
        world_y = -(event.y - self.offset_y) / self.zoom

        if self.dragging_goo:
            self.current_level_data['goo']['x'] = str(round(world_x, 1))
            self.current_level_data['goo']['y'] = str(round(world_y, 1))
            self.redraw_canvas()
        elif self.dragging_emitter and self.selected_emitter_idx != -1:
            emitter = self.current_level_data['emitters'][self.selected_emitter_idx]
            # If it has a path, moving posx/posy won't affect render position in this editor version
            emitter['posx'] = str(round(world_x, 1))
            emitter['posy'] = str(round(world_y, 1))
            self.redraw_canvas()

    def on_release(self, event):
        self.dragging_emitter = False
        self.dragging_goo = False
        if self.selected_emitter_idx != -1 or self.selected_goo:
            # Re-build prop tree to reflect new coordinates
            self.sync_tree_selection()

    def add_emitter(self):
        new_emitter = {
            'type': 'spot',
            'entitydef': 'algea',
            'posx': '0.0',
            'posy': '0.0',
            'minarea': '300.0',
            'maxarea': '300.0',
            'maxlive': '10',
            'controllers': [{'type': 'stationary'}],
            'scheduledemit': [{'time': '0.0'}]
        }
        self.current_level_data['emitters'].append(new_emitter)
        self.update_prop_tree()
        self.redraw_canvas()

    def delete_selected(self):
        if self.selected_emitter_idx != -1:
            if messagebox.askyesno("Confirm", f"Delete Emitter {self.selected_emitter_idx}?"):
                del self.current_level_data['emitters'][self.selected_emitter_idx]
                self.selected_emitter_idx = -1
                self.update_prop_tree()
                self.redraw_canvas()
        else:
            selected = self.tree.selection()
            if not selected: return
            item = self.tree.item(selected[0])
            values = item.get('values')
            if values and (values[2] == "emitter" or values[2] == "emitter_prop"):
                idx = int(values[0]) if values[2] == "emitter" else int(values[3])
                if messagebox.askyesno("Confirm", f"Delete Emitter {idx}?"):
                    del self.current_level_data['emitters'][idx]
                    self.update_prop_tree()
                    self.redraw_canvas()

    def bulk_replace_emitters_dialog(self):
        if not self.current_level_data: return
        
        # Get list of all entities in current level
        current_entities = sorted(list(set(e.get('entitydef') for e in self.current_level_data['emitters'] if e.get('entitydef'))))
        all_entities = sorted(list(self.parser.entitydefs.keys()))

        dialog = tk.Toplevel(self.root)
        dialog.title("Bulk Replace Emitters")
        dialog.geometry("400x220")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Replace all emitters where entitydef is:").pack(pady=(10, 0))
        old_val = ttk.Combobox(dialog, width=40, values=current_entities, state="readonly")
        old_val.pack(pady=5)
        
        # Prefill if an emitter is selected
        if self.selected_emitter_idx != -1:
            e = self.current_level_data['emitters'][self.selected_emitter_idx]
            old_val.set(e.get('entitydef', ''))

        tk.Label(dialog, text="Change them to:").pack(pady=(10, 0))
        new_val = ttk.Combobox(dialog, width=40, values=all_entities, state="readonly")
        new_val.pack(pady=5)
        
        def do_replace():
            old_name = old_val.get().strip()
            new_name = new_val.get().strip()
            if not old_name or not new_name: return
            
            count = 0
            for e in self.current_level_data['emitters']:
                if e.get('entitydef') == old_name:
                    e['entitydef'] = new_name
                    count += 1
            
            if count > 0:
                self.update_prop_tree()
                self.redraw_canvas()
                messagebox.showinfo("Bulk Replace", f"Successfully replaced {count} emitters.")
                dialog.destroy()
            else:
                messagebox.showwarning("Not Found", f"No emitters found with entitydef '{old_name}'")
            
        tk.Button(dialog, text="Replace All", command=do_replace, bg="gray70").pack(pady=15)

    def bulk_replace_tiles_dialog(self):
        if not self.current_level_data: return

        # Get list of all tiles in current level
        current_tiles = set()
        for layer in self.current_level_data.get('tilelayers', []):
            for t in layer.get('tiles', []):
                name = t if isinstance(t, str) else t.get('name')
                if name: current_tiles.add(name)
        
        current_tiles = sorted(list(current_tiles))
        all_tiles = sorted(list(self.parser.tiledefs.keys()))

        dialog = tk.Toplevel(self.root)
        dialog.title("Bulk Replace Tiles")
        dialog.geometry("400x220")
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(dialog, text="Replace all tiles named:").pack(pady=(10, 0))
        old_val = ttk.Combobox(dialog, width=40, values=current_tiles, state="readonly")
        old_val.pack(pady=5)
        
        # Prefill if a tile is selected
        if self.selected_tile_info:
            layer_idx, tile_idx = self.selected_tile_info
            tile = self.current_level_data['tilelayers'][layer_idx]['tiles'][tile_idx]
            name = tile if isinstance(tile, str) else tile.get('name', '')
            old_val.set(name)

        tk.Label(dialog, text="Change them to:").pack(pady=(10, 0))
        new_val = ttk.Combobox(dialog, width=40, values=all_tiles, state="readonly")
        new_val.pack(pady=5)
        
        def do_replace():
            old_name = old_val.get().strip()
            new_name = new_val.get().strip()
            if not old_name or not new_name: return
            
            count = 0
            for layer in self.current_level_data.get('tilelayers', []):
                tiles = layer.get('tiles', [])
                for i in range(len(tiles)):
                    if isinstance(tiles[i], str):
                        if tiles[i] == old_name:
                            tiles[i] = new_name
                            count += 1
                    elif isinstance(tiles[i], dict):
                        if tiles[i].get('name') == old_name:
                            tiles[i]['name'] = new_name
                            count += 1
            
            if count > 0:
                self.update_prop_tree()
                self.redraw_canvas()
                messagebox.showinfo("Bulk Replace", f"Successfully replaced {count} tiles.")
                dialog.destroy()
            else:
                messagebox.showwarning("Not Found", f"No tiles found named '{old_name}'")
            
        tk.Button(dialog, text="Replace All", command=do_replace, bg="gray70").pack(pady=15)

    def update_prop_tree(self):
        if self.updating_tree: return
        self.updating_tree = True
        
        # Update visibility toggles frame
        for child in self.layers_visibility_frame.winfo_children():
            child.destroy()
        
        if self.current_level_data:
            for layer_idx in range(len(self.current_level_data.get('tilelayers', []))):
                if layer_idx not in self.visible_layers:
                    self.visible_layers[layer_idx] = True
                
                var = tk.BooleanVar(value=self.visible_layers[layer_idx])
                cb = tk.Checkbutton(self.layers_visibility_frame, text=f"Layer {layer_idx}", 
                                    variable=var, command=lambda i=layer_idx: self.toggle_layer(i))
                cb.pack(side=tk.LEFT)
        
        # Clear mappings
        self.tile_items = {}
        self.emitter_items = {}
        self.goo_item = None
        self.layer_items = {}
        
        # Clear existing
        for i in self.tree.get_children():
            self.tree.delete(i)
        
        if not self.current_level_data:
            self.updating_tree = False
            return
            
        level_root = self.tree.insert("", "end", text=f"Level: {self.current_level_name}", open=True)
        
        props = self.tree.insert(level_root, "end", text="General Properties", open=False)
        for k, v in self.current_level_data['properties'].items():
            self.tree.insert(props, "end", text=k, values=(v, "prop", k))
            
        goo_data = self.current_level_data.get('goo')
        if goo_data:
            tags = ("selected",) if self.selected_goo else ()
            self.goo_item = self.tree.insert(level_root, "end", text="Goo Spawn", 
                                            values=("", "goo", ""), open=True, tags=tags)
            for k, v in goo_data.items():
                self.tree.insert(self.goo_item, "end", text=k, values=(v, "goo_prop", k))

        emitters_root = self.tree.insert(level_root, "end", text="Emitters", open=True)
        for i, emitter in enumerate(self.current_level_data['emitters']):
            tags = ("selected",) if i == self.selected_emitter_idx else ()
            e_id = self.tree.insert(emitters_root, "end", text=f"Emitter {i}: {emitter.get('entitydef')}", 
                                   values=("", "emitter", i), tags=tags)
            self.emitter_items[i] = e_id
            for k, v in emitter.items():
                if k not in ['controllers', 'randomemit', 'left', 'right', 'top', 'bottom', 'scheduledemit']:
                    self.tree.insert(e_id, "end", text=k, values=(v, "emitter_prop", i, k))
            
            # Show Controllers
            if emitter.get('controllers'):
                c_root = self.tree.insert(e_id, "end", text="Controllers", open=False)
                for ci, ctrl in enumerate(emitter['controllers']):
                    c_id = self.tree.insert(c_root, "end", text=f"Ctrl {ci}: {ctrl.get('type')}", 
                                           values=("", "controller", i, ci))
                    for ck, cv in ctrl.items():
                        if ck not in ['affects', 'dontaffects', 'pairs']:
                            self.tree.insert(c_id, "end", text=ck, values=(cv, "controller_prop", i, ci, ck))
            
            # Show Scheduled Emit
            if emitter.get('scheduledemit'):
                s_root = self.tree.insert(e_id, "end", text="Scheduled Emit", open=False)
                for si, semit in enumerate(emitter['scheduledemit']):
                    s_id = self.tree.insert(s_root, "end", text=f"Emit {si}", values=("", "scheduledemit", i, si))
                    for sk, sv in semit.items():
                        self.tree.insert(s_id, "end", text=sk, values=(sv, "scheduledemit_prop", i, si, sk))
            
            # Show Random Emit
            if emitter.get('randomemit'):
                r_id = self.tree.insert(e_id, "end", text="Random Emit", values=("", "randomemit", i))
                for rk, rv in emitter['randomemit'].items():
                    self.tree.insert(r_id, "end", text=rk, values=(rv, "randomemit_prop", i, rk))

        tiles_root = self.tree.insert(level_root, "end", text="Background Layers", open=True)
        for layer_idx, layer in enumerate(self.current_level_data.get('tilelayers', [])):
            cols = int(layer.get('tileswide', 1))
            rows = int(layer.get('tileshigh', 1))
            
            layer_id = self.tree.insert(tiles_root, "end", text=f"Layer {layer_idx} ({cols}x{rows})", 
                                       values=("", "layer", layer_idx))
            self.layer_items[layer_idx] = layer_id
            
            # Use Row groups, but do NOT populate them yet (Lazy Loading)
            for row in range(rows):
                row_item = self.tree.insert(layer_id, "end", text=f"Row {row}", values=("", "row", layer_idx, row))
                # Insert dummy to make it expandable
                self.tree.insert(row_item, "end", text="Loading...")
        
        self.updating_tree = False
        self.sync_tree_selection()

    def on_tree_open(self, event):
        if self.updating_tree: return
        item = self.tree.focus()
        self.populate_item_children(item)

    def populate_item_children(self, item):
        values = self.tree.item(item, 'values')
        if not values or len(values) < 2: return
        
        v_type = values[1]
        if v_type == "row":
            # Check if already populated
            children = self.tree.get_children(item)
            if len(children) == 1 and self.tree.item(children[0], 'text') == "Loading...":
                self.tree.delete(children[0])
                
                layer_idx = int(values[2])
                row = int(values[3])
                
                layer = self.current_level_data['tilelayers'][layer_idx]
                tiles = layer.get('tiles', [])
                cols = int(layer.get('tileswide', 1))
                
                for col in range(cols):
                    idx = row * cols + col
                    if idx >= len(tiles): break
                    
                    tile = tiles[idx]
                    if isinstance(tile, str):
                        name = tile
                    else:
                        name = tile.get('name', 'unknown')
                    
                    t_id = self.tree.insert(item, "end", text=f"Tile {idx} ({col},{row}): {name}", 
                                           values=(name, "tile", layer_idx, idx))
                    self.tile_items[(layer_idx, idx)] = t_id

    def sync_tree_selection(self):
        if self.updating_tree: return
        self.updating_tree = True
        
        target_item = None
        if self.selected_emitter_idx != -1:
            target_item = self.emitter_items.get(self.selected_emitter_idx)
        elif self.selected_goo:
            target_item = self.goo_item
        elif self.selected_tile_info:
            target_item = self.tile_items.get(self.selected_tile_info)
            if not target_item:
                # If tile item doesn't exist, we must find and populate its row
                layer_idx, tile_idx = self.selected_tile_info
                layer = self.current_level_data['tilelayers'][layer_idx]
                cols = int(layer.get('tileswide', 1))
                row = tile_idx // cols
                
                # Find row item
                layer_item = self.layer_items.get(layer_idx)
                if layer_item:
                    for r_item in self.tree.get_children(layer_item):
                        r_vals = self.tree.item(r_item, 'values')
                        if r_vals and r_vals[1] == "row" and int(r_vals[3]) == row:
                            self.populate_item_children(r_item)
                            target_item = self.tile_items.get(self.selected_tile_info)
                            break
            
        if target_item:
            # Only change selection if it's different to avoid loops
            current_sel = self.tree.selection()
            if not current_sel or current_sel[0] != target_item:
                # Ensure visible
                parent = self.tree.parent(target_item)
                while parent:
                    self.tree.item(parent, open=True)
                    parent = self.tree.parent(parent)
                
                self.tree.selection_set(target_item)
                self.tree.see(target_item)
            
            # Lazy populate tile properties etc.
            if self.selected_tile_info:
                if not self.tree.get_children(target_item):
                    layer_idx, i = self.selected_tile_info
                    tile = self.current_level_data['tilelayers'][layer_idx]['tiles'][i]
                    if isinstance(tile, str):
                        self.current_level_data['tilelayers'][layer_idx]['tiles'][i] = {'name': tile}
                        tile = self.current_level_data['tilelayers'][layer_idx]['tiles'][i]
                    for k, v in tile.items():
                        self.tree.insert(target_item, "end", text=k, values=(v, "tile_prop", layer_idx, i, k))

        self.updating_tree = False

    def on_tree_select(self, event):
        if self.updating_tree: return
        selected = self.tree.selection()
        if not selected: return
        
        item = self.tree.item(selected[0])
        values = item.get('values')
        
        if not values or len(values) < 2: return
        
        v_type = values[1]
        
        if v_type == "emitter":
            idx = int(values[2])
            if self.selected_emitter_idx != idx:
                self.selected_emitter_idx = idx
                self.selected_tile_info = None
                self.selected_goo = False
                self.redraw_canvas()
                self.sync_tree_selection()
        elif v_type == "emitter_prop":
            idx = int(values[2])
            if self.selected_emitter_idx != idx:
                self.selected_emitter_idx = idx
                self.selected_tile_info = None
                self.selected_goo = False
                self.redraw_canvas()
                self.sync_tree_selection()
        elif v_type == "goo" or v_type == "goo_prop":
            if not self.selected_goo:
                self.selected_goo = True
                self.selected_emitter_idx = -1
                self.selected_tile_info = None
                self.redraw_canvas()
                self.sync_tree_selection()
        elif v_type == "tile":
            info = (int(values[2]), int(values[3]))
            if self.selected_tile_info != info:
                self.selected_tile_info = info
                self.selected_emitter_idx = -1
                self.selected_goo = False
                self.redraw_canvas()
                self.sync_tree_selection()
        elif v_type == "tile_prop":
            info = (int(values[2]), int(values[3]))
            if self.selected_tile_info != info:
                self.selected_tile_info = info
                self.selected_emitter_idx = -1
                self.selected_goo = False
                self.redraw_canvas()
                self.sync_tree_selection()

    def on_tree_double_click(self, event):
        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        
        if not item_id or column != "#1": return # Only edit the "Value" column
        
        item = self.tree.item(item_id)
        values = list(item.get('values'))
        if not values or len(values) < 2: return
        
        v_type = values[1]
        if v_type not in ["prop", "emitter_prop", "tile", "tile_prop", "goo_prop", "controller_prop", "scheduledemit_prop", "randomemit_prop"]: return

        # Determine if we should use a Combobox
        use_combo = False
        combo_values = []
        
        if v_type == "emitter_prop" and values[3] == "entitydef":
            use_combo = True
            combo_values = sorted(list(self.parser.entitydefs.keys()))
        elif v_type == "controller_prop" and values[4] == "type":
            use_combo = True
            combo_values = ["stationary", "circular", "random", "follow", "flee", "hover"] # Common types
        elif v_type == "tile":
            use_combo = True
            combo_values = sorted(list(self.parser.tiledefs.keys()))
        elif v_type == "tile_prop" and values[4] == "name":
            use_combo = True
            combo_values = sorted(list(self.parser.tiledefs.keys()))

        # Create an entry or combo widget over the cell
        x, y, w, h = self.tree.bbox(item_id, column)
        
        if use_combo:
            editor = ttk.Combobox(self.tree, values=combo_values, state="readonly")
        else:
            editor = tk.Entry(self.tree)
            
        initial_val = values[0]
        if v_type == "tile":
            # Extract name from text if values[0] is empty
            tile_node_text = item.get('text', "")
            if ": " in tile_node_text:
                initial_val = tile_node_text.split(": ")[1]
        
        if use_combo:
            editor.set(initial_val)
        else:
            editor.insert(0, initial_val)
            
        editor.place(x=x, y=y, width=w, height=h)
        editor.focus_set()

        def save_edit(event=None):
            new_val = editor.get()
            if v_type == "prop":
                key = values[2]
                self.current_level_data['properties'][key] = new_val
            elif v_type == "emitter_prop":
                idx = int(values[2])
                key = values[3]
                self.current_level_data['emitters'][idx][key] = new_val
            elif v_type == "tile":
                layer_idx = int(values[2])
                tile_idx = int(values[3])
                # Changing the name of the tile texture
                tile = self.current_level_data['tilelayers'][layer_idx]['tiles'][tile_idx]
                if isinstance(tile, str):
                    self.current_level_data['tilelayers'][layer_idx]['tiles'][tile_idx] = new_val
                else:
                    tile['name'] = new_val
            elif v_type == "tile_prop":
                layer_idx = int(values[2])
                tile_idx = int(values[3])
                key = values[4]
                self.current_level_data['tilelayers'][layer_idx]['tiles'][tile_idx][key] = new_val
            elif v_type == "goo_prop":
                key = values[2]
                self.current_level_data['goo'][key] = new_val
            elif v_type == "controller_prop":
                e_idx = int(values[2])
                c_idx = int(values[3])
                key = values[4]
                self.current_level_data['emitters'][e_idx]['controllers'][c_idx][key] = new_val
            elif v_type == "scheduledemit_prop":
                e_idx = int(values[2])
                s_idx = int(values[3])
                key = values[4]
                self.current_level_data['emitters'][e_idx]['scheduledemit'][s_idx][key] = new_val
            elif v_type == "randomemit_prop":
                e_idx = int(values[2])
                key = values[3]
                self.current_level_data['emitters'][e_idx]['randomemit'][key] = new_val
            
            editor.destroy()
            self.update_prop_tree()
            self.redraw_canvas()

        if use_combo:
            editor.bind("<<ComboboxSelected>>", save_edit)
        
        editor.bind("<Return>", save_edit)
        editor.bind("<Escape>", lambda e: editor.destroy())
        
        # Safe focus handling
        def on_focus_out(event):
            # For Combobox, clicking the arrow triggers focus out, so we need to be careful
            # But in simple cases, just destroying is often enough if the user clicked away
            if editor.winfo_exists():
                editor.destroy()
        
        editor.bind("<FocusOut>", on_focus_out)

    def update_level_prop(self, key, val):
        self.current_level_data['properties'][key] = val

    def update_emitter_prop(self, idx, key, val):
        self.current_level_data['emitters'][idx][key] = val

    def save_current_level(self):
        if self.current_level_data and self.current_level_name:
            self.parser.save_level(self.current_level_data, self.current_level_name)
            messagebox.showinfo("Success", f"Saved {self.current_level_name}.xml")

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = LevelEditorApp(root)
        root.mainloop()
    except Exception as e:
        # Fallback if tk is not working
        try:
            import tkinter.messagebox as mb
            mb.showerror("Startup Error", str(e))
        except:
            pass

