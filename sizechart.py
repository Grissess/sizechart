from xml.etree import ElementTree as ET
import argparse
import math
import glob
import traceback
import os
import operator

import pyglet
from pyglet.window import key, mouse
from pygame import Rect
import pygame

NS = {
    'svg': 'http://www.w3.org/2000/svg',
    'xlink': 'http://www.w3.org/1999/xlink',
    'sizechart': 'urn:grissess:sizechart',
}

def ns(n, t):
    return f'{{{NS[n]}}}{t}'

CURSOR = '|'

def steps(origin, width, bias = 0.25):
    try:
        step = 10 ** (int(math.log(width, 10) - bias))
    except ValueError:
        step = 1
    nearest = int(origin / step) * step
    x = nearest
    while x <= origin+width:
        yield x
        x += step

class Vec2:
    def __init__(self, x=0, y=0):
        self.x, self.y = x, y

    def __repr__(self):
        return f'{type(self).__name__}{(self.x, self.y)!r}'

    def __len__(self): return 2
    def __getitem__(self, i): return (self.x, self.y)[i]
    def __setitem__(self, i, v): setattr(self, 'xy'[i], v)
    def __iter__(self): return iter((self.x, self.y))

    @classmethod
    def into(cls, v):
        if isinstance(v, cls):
            return v
        return cls(v, v)

    def broadcast(self, op, other):
        return type(self)(*(op(i, j) for i, j in zip(self, other)))

    def __add__(self, rhs): return self.broadcast(operator.add, self.into(rhs))
    __radd__ = __add__
    def __sub__(self, rhs): return self.broadcast(operator.sub, self.into(rhs))
    def __rsub__(self, lhs): return self.into(lhs).broadcast(operator.sub, self)
    def __mul__(self, rhs): return self.broadcast(operator.mul, self.into(rhs))
    __rmul__ = __mul__
    def __truediv__(self, rhs): return self.broadcast(operator.truediv, self.into(rhs))
    def __rtruediv__(self, lhs): return self.into(lhs).broadcast(operator.truediv, self)
    def __floordiv__(self, rhs): return self.broadcast(operator.floordiv, self.into(rhs))
    def __rfloordiv__(self, lhs): return self.into(lhs).broadcast(operator.floordiv, self)
    def __mod__(self, rhs): return self.broadcast(operator.mod, self.into(rhs))
    def __rmod__(self, lhs): return self.into(lhs).broadcast(operator.mod, self)

class Canvas:
    def __init__(self, disp, origin = Vec2(), scale=0.01):
        self.disp, self.origin, self.scale = disp, origin, scale
        self.font = pygame.font.Font(None, 24)

    @property
    def viewbox(self):
        w, h = self.disp.get_size()
        x, y = self.origin
        return Rect(x, y, w / self.scale, h / self.scale)

    def map_scaled(self, p):
        return p * self.scale

    def map_point(self, p):
        return self.map_scaled(p - self.origin)

    def unmap_scaled(self, p):
        return p / self.scale

    def unmap_point(self, p):
        return self.unmap_scaled(p) + self.origin

    def move(self, dx=0, dy=0):
        self.origin += Vec2(dx, dy)

    def scale_into(self, scale, pos):
        # No part of this works and I don't know why
        # but it barely works, so here we go
        delta = pos - self.origin
        olds = self.scale
        self.scale *= scale
        newscale = self.scale * scale
        ds = newscale - olds
        pan = delta * ds / self.scale / 2
        #print(f'scale_into: scale={scale} pos={pos} delta={delta} ds={ds} pan={pan}')
        self.origin += pan

    def clear(self):
        self.disp.clear()

    def draw_sprite(self, spr):
        old_scale = spr.scale
        old_pos = spr.position

        spr.x = (spr.x - self.origin.x) * self.scale
        spr.y = (spr.y - self.origin.y) * self.scale
        spr.scale *= self.scale
        spr.draw()

        spr.scale = old_scale
        spr.position = old_pos

    def draw_rect(self, r, color=(255, 255, 255), stroke=True, fill=False):
        p = self.map_point(Vec2(r.x, r.y))
        s = self.map_scaled(Vec2(r.w, r.h))
        if fill:
            pyglet.shapes.Rectangle(
                    x = p.x, y = p.y,
                    width = s.x, height = s.y,
                    color = color,
            ).draw()
        if stroke:
            pts = [p, p + Vec2(s.x, 0), p+s, p + Vec2(0, s.y), p]
            line = pyglet.shapes.Line(0, 0, 0, 0, color=color)
            for a, b in zip(pts, pts[1:]):
                line.x, line.y = a
                line.x2, line.y2 = b
                line.draw()

    def draw_line(self, a, b, color=(255, 255, 255), width=1):
        a, b = self.map_point(a), self.map_point(b)
        pyglet.shapes.Line(
            a.x, a.y, b.x, b.y,
            width = width,
            color = color,
        ).draw()

    def draw_text(self, s, p, color=(255, 255, 255), anchor_x='left', anchor_y='baseline'):
        #print(f'text {s} {p} {color}')
        p = self.map_point(p)
        pyglet.text.Label(
            s,
            x = p.x, y = p.y,
            color = color + (255,),
            font_size = 24,
            anchor_x = anchor_x, anchor_y = anchor_y,
        ).draw()

class Sprite:
    def __init__(self, img, path, scale=1.0, olap = 0.75, y = 0.0, refy = None):
        self.img, self.path, self.scale, self.olap, self.y = img, path, scale, olap, y
        self.sprite = pyglet.sprite.Sprite(img=self.img)
        self.refy = refy
        self.lastx = None

    @classmethod
    def from_element(cls, elem):
        path = elem.get('href', elem.get(ns('xlink', 'href')))
        try:
            surf = pyglet.image.load(path)
        except FileNotFoundError:
            surf = pyglet.resource.image('notfound.png')
        scale = float(elem.get(ns('sizechart', 'scale'), 1.0))
        olap = float(elem.get(ns('sizechart', 'overlap'), 0.75))
        y = float(elem.get(ns('sizechart', 'offsetY'), 0.0))
        ry = elem.get(ns('sizechart', 'referenceY'))
        if ry is not None:
            ry = float(ry)
        return cls(surf, path, scale, olap, y, ry)

    REF_COLOR = (255, 0, 255)
    def draw(self, canv, x, app):
        self.lastx = x
        self.sprite.update(
            x = x,
            y = self.y * self.scale,
            scale = self.scale,
        )
        canv.draw_sprite(self.sprite)

        if self.refy is not None:
            y = self.scale * (self.refy + self.y)
            canv.draw_line(
                Vec2(x, y),
                Vec2(x + self.sprite.width, y),
                color = self.REF_COLOR,
            )

            u = app.unit if app.real_units else 'px'
            dy = y
            if app.real_units:
                dy /= app.ppu
            canv.draw_text(
                f'{dy:.3f}{u}',
                Vec2(x, y),
                color = self.REF_COLOR,
            )
        return x + self.sprite.width * self.olap

    def box(self, canv, x, color=(255, 255, 255)):
        canv.draw_rect(pygame.Rect(
                x, self.scale * self.y,
                self.sprite.width,
                self.sprite.height,
            ), color,
        )

    @property
    def rect(self):
        if self.lastx is None:
            return
        r = Rect(0, 0, self.sprite.width, self.sprite.height)
        r.x = self.lastx
        r.y = self.scale * self.y
        print(f'spr rect {r}')
        return r

    def contains(self, cpt):
        return self.rect.collidepoint(cpt)

    def save(self, tb, vh):
        attrs = {
                'href': self.path,
                'x': str(self.lastx),
                'y': str(vh - self.scale * self.y - self.sprite.height),
                'width': str(self.sprite.width),
                'height': str(self.sprite.height),
                ns('sizechart', 'origWidth'): str(self.sprite.image.width),
                ns('sizechart', 'origHeight'): str(self.sprite.image.height),
                ns('sizechart', 'scale'): str(self.scale),
                ns('sizechart', 'overlap'): str(self.olap),
                ns('sizechart', 'offsetY'): str(self.y),
                ns('sizechart', 'role'): 'Sprite',
        }
        if self.refy is not None:
            attrs[ns('sizechart', 'referenceY')] = str(self.refy)
        tb.start(ns('svg', 'image'), attrs)
        tb.end(ns('svg', 'image'))

class Event:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class App:
    def __init__(self, screen):
        self.canvas = Canvas(screen)
        self.sprites = []
        self.selection = None
        self.running = True
        self.keystate = self.ks_default
        self.grid_fore = False
        self.ppu = 128.0
        self.real_units = True
        self.unit = 'm'
        self.capture = False
        self.buffer = ''
        self.message = ''
        self.mpos = Vec2()
        self.mods = 0
        screen.push_handlers(
            on_key_press = self.ev_key_press,
            on_key_release = self.ev_key_release,
            on_text = self.ev_text,
            on_text_motion = self.ev_text_motion,
            on_mouse_press = self.ev_mouse_press,
            on_mouse_release = self.ev_mouse_release,
            on_mouse_motion = self.ev_mouse_motion,
            on_mouse_drag = self.ev_mouse_drag,
            on_mouse_scroll = self.ev_mouse_scroll,
            on_draw = self.render,
        )

    def save_tree(self):
        tb = ET.TreeBuilder()

        r = Rect(0, 0, 1, 1)
        for spr in self.sprites:
            r.union_ip(spr.rect)
        vh = r.h
        vb = f'0 0 {r.w - r.x} {r.h - r.y}'

        tb.start(ns('svg', 'svg'), {
            ns('svg', 'viewbox'): vb,
            'width': str(r.w - r.x),
            'height': str(r.h - r.y),
            # 'style': 'background-color: #000;',
            ns('sizechart', 'ppu'): str(self.ppu),
            ns('sizechart', 'unit'): self.unit,
            ns('sizechart', 'canvasX'): str(self.canvas.origin[0]),
            ns('sizechart', 'canvasY'): str(self.canvas.origin[1]),
            ns('sizechart', 'canvasScale'): str(self.canvas.scale),
        })

        self.svg_scale(tb, r)

        for spr in self.sprites:
            spr.save(tb, vh)

        tb.end(ns('svg', 'svg'))
        return ET.ElementTree(tb.close())

    def svg_scale(self, tb, r):
        major = set()
        fw = r.w - r.x
        for y in steps(0, r.h / self.ppu):
            major.add(y)
        for y in steps(0, r.h / self.ppu, 1.25):
            sy = r.h - y * self.ppu
            tb.start(ns('svg', 'line'), {
                'x1': '0',
                'x2': str(fw),
                'y1': str(sy),
                'y2': str(sy),
                'stroke': '#077' if abs(y) < 0.001 else '#770',
                'stroke-width': '3' if y in major else '1',
            })
            tb.end(ns('svg', 'line'))
            tb.start(ns('svg', 'text'), {
                'x': '0',
                'y': str(sy),
                'dominant-baseline': 'hanging',
                'fill': '#770',
                'dy': '3',
            })
            tb.data(f'{y}{self.unit}')
            tb.end(ns('svg', 'text'))

    def load_tree(self, root):
        self.ppu = float(root.get(ns('sizechart', 'ppu'), self.ppu))
        self.unit = root.get(ns('sizechart', 'unit'), self.unit)
        self.canvas.origin = Vec2(
            float(root.get(ns('sizechart', 'canvasX'), self.canvas.origin[0])),
            float(root.get(ns('sizechart', 'canvasY'), self.canvas.origin[1])),
        )
        self.canvas.scale = float(root.get(
            ns('sizechart', 'canvasScale'),
            self.canvas.scale,
        ))
        del self.sprites[:]
        for child in root:
            if child.get(ns('sizechart', 'role')) == 'Sprite':
                self.sprites.append(Sprite.from_element(child))

    SEL_COLOR = (255, 128, 0)
    def render(self):
        self.canvas.clear()
        if not self.grid_fore:
            self.render_grid()
        x = 0.0
        for i, spr in enumerate(self.sprites):
            nx = spr.draw(self.canvas, x, self)
            if i == self.selection:
                spr.box(self.canvas, x, self.SEL_COLOR)
            x = nx
        if self.grid_fore:
            self.render_grid()
        self.render_mouse()
        self.render_hud()

    PIX_GRID_COLOR = (255, 255, 255)
    REAL_GRID_COLOR = (255, 255, 0)
    ORIGIN_WIDTH = 3
    def render_grid(self):
        vb = self.canvas.viewbox
        rvb = Rect(
            *(i / self.ppu for i in (vb.x, vb.y, vb.w, vb.h))
        )
        r = rvb if self.real_units else vb
        col = self.REAL_GRID_COLOR if self.real_units else self.PIX_GRID_COLOR

        for y in steps(r.y, r.h):
            vy = y * self.ppu if self.real_units else y
            w = self.ORIGIN_WIDTH if abs(y) <= 0.001 else 1
            self.canvas.draw_line(
                Vec2(vb.x, vy), Vec2(vb.x + vb.w, vy),
                color = col, width = w,
            )
            self.canvas.draw_text(
                f'{y:.3f}{self.unit if self.real_units else "px"}',
                Vec2(vb.x, vy),
                color = col,
            )

        for x in steps(r.x, r.w):
            vx = x * self.ppu if self.real_units else x
            w = self.ORIGIN_WIDTH if abs(x) <= 0.001 else 1
            self.canvas.draw_line(
                Vec2(vx, vb.y), Vec2(vx, vb.y + vb.h),
                color = col, width = w,
            )
            self.canvas.draw_text(
                f'{x:.3f}{self.unit if self.real_units else "px"}',
                Vec2(vx, 0),
                color = col,
            )

    def hit_test(self, cpt):
        print(f'hit {cpt}')
        for ix, spr in enumerate(self.sprites):
            if spr.contains(cpt):
                return ix, spr
        return None, None

    MOUSE_COLOR = (0, 255, 255)
    def render_mouse(self):
        u = self.canvas.unmap_point(self.mpos)
        self.canvas.draw_line(
            u - Vec2(5, 0),
            u + Vec2(5, 0),
            self.MOUSE_COLOR,
        )
        self.canvas.draw_line(
            u - Vec2(0, 5),
            u + Vec2(0, 5),
            self.MOUSE_COLOR,
        )
        cu = u
        if self.real_units:
            unit = self.unit
            cu /= self.ppu
        else:
            unit = "px"
        self.canvas.draw_text(
            f'{cu.x:.3f}{unit},{cu.y:.3f}{unit}',
            u,
            self.MOUSE_COLOR,
        )

    HUD_COLOR = (0, 0, 255)
    def render_hud(self):
        self.canvas.draw_text(
            self.message,
            self.canvas.unmap_point(Vec2(0, self.canvas.disp.get_size()[1] - 12)),
            self.HUD_COLOR,
        )
        #self.canvas.disp.fill(
        #    (0, 0, 0, 32),
        #    (0, 0, self.canvas.disp.get_width(), s.get_height())
        #)
        #self.canvas.disp.blit(s, (0, 0))

        cp = self.canvas.unmap_point(self.mpos)
        u = self.unit if self.real_units else "px"
        if self.real_units:
            cp = tuple(i / self.ppu for i in cp)
        cx, cy = cp
        lines = [
            f'Cursor: {cx:.3f}{u},{cy:.3f}{u}',
        ]
        if self.real_units:
            lines.extend([
                f'Scale: {self.ppu}px/{self.unit}',
            ])
        if self.selection is not None:
            spr = self.sprites[self.selection]
            sw, sh = spr.sprite.width, spr.sprite.height
            ref = None
            if spr.refy is not None:
                ry = spr.scale * spr.refy
                y = spr.scale * (spr.refy + spr.y)
                dy, dry = y, ry
                u = "px"
                if self.real_units:
                    dy, dry = tuple(i / self.ppu for i in (dy, dry))
                    u = self.unit
                ref = f'{dy:.3f}{u} ({dry:.3f}{u} baseline)'
            lines.extend([
                f'Index: {self.selection}',
                f'Path: {spr.path}',
                f'Scale: {spr.scale:.3f}',
                f'Y-offset: {spr.y:.3f}',
                f'Rendered X: {spr.lastx:.3f}',
                f'Overlap: {spr.olap:.3f}',
                f'Pixel Size: {sw:.3f},{sh:.3f}',
                f'Ref: {ref}',
            ])

        cw = self.canvas.disp.get_size()[0]
        #mw = max(i.get_width() for i in surfs)
        #mw = 240
        #x = self.canvas.disp.get_size()[0] - mw
        y = 0
        for line in lines:
            self.canvas.draw_text(
                line,
                self.canvas.unmap_point(Vec2(cw, y)),
                self.HUD_COLOR,
                anchor_x = 'right',
            )
            y += 24

    def ev_key_press(self, key, mod):
        self.mods = mod
        self.keystate(Event(
            type=pygame.KEYDOWN,
            key=key,
            mod=mod,
        ))

    def ev_key_release(self, key, mod):
        self.mods = mod
        self.keystate(Event(
            type=pygame.KEYUP,
            key=key,
            mod=mod,
        ))

    def ev_mouse_motion(self, x, y, dx, dy):
        self.mpos = Vec2(x, y)
        self.keystate(Event(
            type=pygame.MOUSEMOTION,
            pos=self.mpos,
        ))

    def ev_mouse_drag(self, x, y, dx, dy, button, mods):
        self.mods = mods
        self.mpos = Vec2(x, y)
        self.keystate(Event(
            type=pygame.MOUSEMOTION,
            pos=self.mpos,
        ))

    def ev_mouse_scroll(self, x, y, sx, sy):
        self.mpos = Vec2(x, y)
        if sy != 0:
            self.keystate(Event(
                type=pygame.MOUSEBUTTONDOWN,
                pos=self.mpos,
                mod=0,
                button = 4 if sy > 0 else 5,
            ))

    def ev_mouse_press(self, x, y, button, mods):
        self.mods = mods
        self.mpos = Vec2(x, y)
        self.keystate(Event(
            type=pygame.MOUSEBUTTONDOWN,
            pos=self.mpos,
            button=button,
            mod=mods,
        ))

    def ev_mouse_release(self, x, y, button, mods):
        self.mods = mods
        self.mpos = Vec2(x, y)
        self.keystate(Event(
            type=pygame.MOUSEBUTTONUP,
            pos=self.mpos,
            button=button,
            mod=mods,
        ))

    def ev_text(self, text):
        if self.capture:
            self.buffer += text

    def ev_text_motion(self, motion):
        if self.capture:
            if motion == key.MOTION_BACKSPACE:
                self.buffer = self.buffer[:-1]

    def sel_offset(self, ds):
        if not self.sprites:
            self.selection = None
        else:
            if self.selection is None:
                self.selection = 0 if ds > 0 else (len(self.sprites) - 1)
            else:
                self.selection = (self.selection + ds) % len(self.sprites)

    def add_to_buffer(self, ev):
        pass

    def ks_default(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == key.UP:
                if ev.mod & key.MOD_ACCEL:
                    self.canvas.scale *= 2.0
                elif ev.mod & key.MOD_ALT:
                    self.selection = None
                elif ev.mod == 0:
                    self.canvas.move(dy=0.1 * self.canvas.viewbox.h)
            elif ev.key == key.DOWN:
                if ev.mod & key.MOD_ACCEL:
                    self.canvas.scale /= 2.0
                elif ev.mod == 0:
                    self.canvas.move(dy=-0.1 * self.canvas.viewbox.h)
            elif ev.key == key.LEFT:
                if ev.mod == 0:
                    self.canvas.move(dx=-0.1 * self.canvas.viewbox.w)
                elif ev.mod & key.MOD_ALT:
                    self.sel_offset(-1)
                elif ev.mod & key.MOD_ACCEL:
                    if self.selection is not None and self.selection > 0:
                        self.sprites[self.selection], self.sprites[self.selection - 1] = \
                            self.sprites[self.selection - 1], self.sprites[self.selection]
                        self.selection -= 1
            elif ev.key == key.RIGHT:
                if ev.mod == 0:
                    self.canvas.move(dx=0.1 * self.canvas.viewbox.w)
                elif ev.mod & key.MOD_ALT:
                    self.sel_offset(1)
                elif ev.mod & key.MOD_ACCEL:
                    if self.selection is not None and self.selection < len(self.sprites) - 1:
                        self.sprites[self.selection], self.sprites[self.selection + 1] = \
                            self.sprites[self.selection + 1], self.sprites[self.selection]
                        self.selection += 1
            elif ev.key == key.G:
                self.grid_fore = True
            elif ev.key == key.R:
                self.real_units = not self.real_units
            elif ev.key == key.Z and self.selection is not None:
                self.keystate = self.ks_reference
            elif ev.key == key.T and self.selection is not None:
                self.origy = self.sprites[self.selection].y
                self.origmy = self.mpos.y
                self.keystate = self.ks_move
            elif ev.key == key.S and self.selection is not None:
                self.origmy = self.mpos.y
                self.keystate = self.ks_scale
            elif ev.key == key.O and self.selection is not None:
                if self.selection > 0:
                    self.origmx = self.mpos.x
                    self.keystate = self.ks_offset
                else:
                    self.message = "Can't offset the first sprite"
            elif ev.key == key.D and self.selection is not None:
                self.message = 'Really delete? (y/n)'
                self.keystate = self.ks_delete
        elif ev.type == pygame.KEYUP:
            if ev.key == key.G:
                self.grid_fore = False
            elif ev.key == key.L:
                self.buffer = ''
                self.capture = True
                self.message = f'Load: {CURSOR}'
                self.keystate = self.ks_load
            elif ev.key == key.W:
                self.buffer = 'chart.svg'
                self.capture = True
                self.message = f'Write: {self.buffer}{CURSOR}'
                self.keystate = self.ks_write
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.LEFT:
                self.drag_pos = ev.pos
                self.drag_origin = self.canvas.origin
                self.keystate = self.ks_dragging
            elif ev.button == 4:
                pt = self.canvas.unmap_point(ev.pos)
                self.canvas.scale_into(1.1, pt)
            elif ev.button == 5:
                pt = self.canvas.unmap_point(ev.pos)
                self.canvas.scale_into(1/1.1, pt)

    def ks_dragging(self, ev):
        if ev.type == pygame.MOUSEBUTTONUP:
            if ev.pos == self.drag_pos:
                ix, _ = self.hit_test(self.canvas.unmap_point(ev.pos))
                self.selection = ix
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            delta = self.drag_pos - ev.pos
            delta = self.canvas.unmap_scaled(delta)
            self.canvas.origin = self.drag_origin + delta

    def ks_reference(self, ev):
        spr = self.sprites[self.selection]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                spr.refy = None
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            p = self.canvas.unmap_point(ev.pos)
            spr.refy = (p.y - spr.y) / spr.scale
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_0:
                spr.y = -spr.refy
                spr.refy = None
                self.keystate = self.ks_default

    def ks_move(self, ev):
        spr = self.sprites[self.selection]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            d = self.canvas.unmap_scaled(Vec2(0, ev.pos.y - self.origmy))
            spr.y = self.origy + d.y

    def ks_scale(self, ev):
        spr = self.sprites[self.selection]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            d = ev.pos.y - self.origmy
            self.origmy = ev.pos.y
            base = 1.01
            if self.mods & key.MOD_ACCEL:
                base = 1.001
            elif self.mods & key.MOD_SHIFT:
                base = 1.1
            spr.scale *= base**d
            print(f'new scale: {spr.scale}')

    def ks_offset(self, ev):
        spr = self.sprites[self.selection - 1]
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            dx = ev.pos.x - self.origmx
            self.origmx = ev.pos.x
            spr.olap += dx * 0.01

    def ks_load(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == key.ENTER:
                try:
                    spr = Sprite(
                        pyglet.image.load(self.buffer),
                        self.buffer,
                    )
                except FileNotFoundError as e:
                    traceback.print_exc()
                    self.message = repr(e)
                else:
                    if self.selection is not None:
                        self.sprites.insert(self.selection, spr)
                    else:
                        self.sprites.append(spr)
                self.keystate = self.ks_default
                self.message = ''
                self.capture = False
                return
            elif ev.key == key.TAB:
                opts = glob.glob(self.buffer + '*')
                if opts:
                    pfx = os.path.commonprefix(opts)
                    if len(pfx) > len(self.buffer):
                        self.buffer = pfx
            else:
                self.add_to_buffer(ev)
            self.message = f'Load: {self.buffer}{CURSOR}'

    def ks_delete(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == key.Y:
                del self.sprites[self.selection]
                self.selection = None
            self.keystate = self.ks_default
            self.message = ''

    def ks_write(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == key.ENTER:
                et = self.save_tree()
                et.write(self.buffer, 'unicode')
                self.keystate = self.ks_default
                self.message = ''
                self.capture = False
                return
            elif ev.key == key.TAB:
                opts = glob.glob(self.buffer + '*')
                if opts:
                    pfx = os.path.commonprefix(opts)
                    if len(pfx) > len(self.buffer):
                        self.buffer = pfx
            else:
                self.add_to_buffer(ev)
            self.message = f'Write: {self.buffer}{CURSOR}'

def main():
    import sys
    pygame.init()
    pygame.display.set_caption('sizechart')
    app = App(pyglet.window.Window(resizable=True))
    if len(sys.argv) > 1:
        et = ET.ElementTree(file=sys.argv[1])
        app.load_tree(et.getroot())
    clock = pygame.time.Clock()
    # begin test code
    #path = "images/Grissess_Full_transparent.png"
    #gris = pygame.image.load(path)
    #for i in range(3):
    #    app.sprites.append(Sprite(gris, path))
    #app.selection = 1

    pyglet.app.run()

if __name__ == '__main__':
    main()
