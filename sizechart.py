from xml.etree import ElementTree as ET
import argparse
import math
import glob
import traceback
import os
import operator
import time
from enum import Enum, auto
from ctypes import byref

import pyglet
from pyglet.gl import *
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

def mod_for(k):
    if k in {key.LALT, key.RALT}:
        return key.MOD_ALT
    elif k in {key.LCOMMAND, key.RCOMMAND}:
        return key.MOD_COMMAND
    elif k in {key.LCTRL, key.RCTRL}:
        return key.MOD_CTRL
    elif k in {key.LOPTION, key.ROPTION}:
        return key.MOD_OPTION
    elif k in {key.LSHIFT, key.RSHIFT}:
        return key.MOD_SHIFT
    elif k in {key.LWINDOWS, key.RWINDOWS}:
        return key.MOD_WINDOWS
    return 0

class RenderState(Enum):
    NORMAL = auto()
    IMAGE = auto()

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

    def __eq__(self, rhs):
        if not isinstance(rhs, type(self)): return NotImplemented
        return self.x == rhs.x and self.y == rhs.y
    def __ne__(self, rhs):
        return not (self == rhs)

class Canvas:
    def __init__(self, disp, origin = Vec2(), scale=0.01):
        self.disp, self.origin, self.scale = disp, origin, scale
        self.font = pygame.font.Font(None, 24)
        self.target_size = None

    @property
    def view_size(self):
        if self.target_size is not None:
            return self.target_size
        return Vec2(*self.disp.get_size())

    @property
    def viewbox(self):
        w, h = self.view_size
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
    def __init__(self, img, path, scale=1.0, olap = 0.75, y = 0.0, refy = None, name = 'unnamed'):
        self.img, self.path, self.scale, self.olap, self.y = img, path, scale, olap, y
        self.sprite = pyglet.sprite.Sprite(img=self.img)
        self.refy = refy
        self.name = name
        self.lastx = None

    @classmethod
    def from_element(cls, elem):
        path = elem.get('href', elem.get(ns('xlink', 'href')))
        try:
            surf = pyglet.image.load(path)
        except FileNotFoundError:
            surf = pyglet.image.create(
                int(elem.get(ns('sizechart', 'origWidth'), 256)),
                int(elem.get(ns('sizechart', 'origHeight'), 256)),
                pyglet.image.CheckerImagePattern(
                    (255, 0, 255, 255),
                    (0, 0, 0, 255),
                ),
            )
        scale = float(elem.get(ns('sizechart', 'scale'), 1.0))
        olap = float(elem.get(ns('sizechart', 'overlap'), 0.75))
        y = float(elem.get(ns('sizechart', 'offsetY'), 0.0))
        ry = elem.get(ns('sizechart', 'referenceY'))
        if ry is not None:
            ry = float(ry)
        name = elem.get(ns('sizechart', 'name'), 'unnamed')
        return cls(surf, path, scale, olap, y, ry, name)

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
                ns('sizechart', 'name'): self.name,
                ns('sizechart', 'role'): 'Sprite',
        }
        if self.refy is not None:
            attrs[ns('sizechart', 'referenceY')] = str(self.refy)
        tb.start(ns('svg', 'image'), attrs)
        tb.end(ns('svg', 'image'))

class Viewport:
    FBO = None

    def __init__(self, name, rect, scale=1.0):
        self.name = name
        self.rect = rect
        self.scale = scale

    @property
    def render_size(self):
        return self.scale * Vec2(self.rect.w, self.rect.h)

    def save(self, tb):
        tb.start(ns('sizechart', 'viewport'), {
            'x': str(self.rect.x),
            'y': str(self.rect.y),
            'width': str(self.rect.w),
            'height': str(self.rect.h),
            'scale': str(self.scale),
            'name': self.name,
            ns('sizechart', 'role'): 'Viewport',
        })
        tb.end(ns('sizechart', 'viewport'))

    @classmethod
    def from_element(cls, elem):
        r = Rect(
            int(elem.get('x', 0)),
            int(elem.get('y', 0)),
            int(elem.get('width', 1)),
            int(elem.get('height', 1)),
        )
        return cls(
            elem.get('name', 'unknown'),
            r,
            float(elem.get('scale', 1.0)),
        )

    SLACK = 5
    def contains(self, cpt):
        ox, oy = self.rect.x, self.rect.y
        fx, fy = ox + self.rect.w, oy + self.rect.h
        if (abs(cpt.x - ox) < self.SLACK or abs(cpt.x - fx) < self.SLACK) \
                and oy <= cpt.y <= fy:
            return True
        if (abs(cpt.y - oy) < self.SLACK or abs(cpt.y - fy) < self.SLACK) \
                and ox <= cpt.y <= fx:
            return True
        return False

    @property
    def invalid(self):
        return self.rect.w <= 0 or self.rect.h <= 0

    VP_COLOR = (0, 0, 255)
    VP_INVALID = (255, 0, 0)
    VP_SEL = (0, 255, 255)
    def draw(self, canv, sel=False):
        r = self.rect
        if sel:
            col = self.VP_SEL
        elif self.invalid:
            col = self.VP_INVALID
        else:
            col = self.VP_COLOR
        canv.draw_rect(r, col)
        canv.draw_text(
            f'{self.rect.x},{self.rect.y}',
            Vec2(r.x, r.y),
            col,
        )
        canv.draw_text(
            self.name,
            Vec2(r.x + r.w, r.y),
            col,
            anchor_x = 'right',
            anchor_y = 'top',
        )
        hx = r.x + r.w/2
        hy = r.y + r.h/2
        s = self.render_size
        canv.draw_text(
            f'{s.x}px ({r.w}px * {self.scale:.3f})',
            Vec2(hx, r.y),
            col,
            anchor_y='top',
            anchor_x='center',
        )
        canv.draw_text(
            f'{s.y}px ({r.h}px * {self.scale:.3f}',
            Vec2(r.x, hy),
            col,
            anchor_x='right',
        )

    def render(self, app):
        if self.invalid:
            return

        if Viewport.FBO is None:
            Viewport.FBO = GLuint(0)
            glGenFramebuffers(1, byref(Viewport.FBO))

        s = self.render_size
        s.x, s.y = (math.ceil(i) for i in s)
        glBindFramebuffer(GL_FRAMEBUFFER, Viewport.FBO)
        tex = pyglet.image.Texture.create(s.x, s.y)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex.id, 0)
        
        old_scale = app.canvas.scale
        old_origin = app.canvas.origin
        app.canvas.scale = self.scale
        app.canvas.origin = Vec2(self.rect.x, self.rect.y)
        app.canvas.target_size = self.render_size
        app.canvas.disp.projection.set(s.x, s.y, s.x, s.y)
        app.render(RenderState.IMAGE)
        app.canvas.disp.projection.set(
            *app.canvas.disp.get_size(),
            *app.canvas.disp.get_framebuffer_size(),
        )
        app.canvas.target_size = None
        app.canvas.origin = old_origin
        app.canvas.scale = old_scale

        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, *app.canvas.view_size)
        tex.save(self.name)

class Event:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class App:
    def __init__(self, screen):
        self.canvas = Canvas(screen)
        self.sprites = []
        self.viewports = []
        self.selection = []
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
        for vp in self.viewports:
            vp.save(tb)

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
            role = child.get(ns('sizechart', 'role'))
            if role == 'Sprite':
                self.sprites.append(Sprite.from_element(child))
            elif role == 'Viewport':
                self.viewports.append(Viewport.from_element(child))

    SEL_PRIM_COLOR = (255, 128, 0)
    SEL_COLOR = (128, 64, 0)
    def render(self, rs=RenderState.NORMAL):
        self.canvas.clear()
        if not self.grid_fore:
            self.render_grid()
        x = 0.0
        for i, spr in enumerate(self.sprites):
            nx = spr.draw(self.canvas, x, self)
            if spr in self.selection:
                col = self.SEL_COLOR
                if spr is self.primary_selection:
                    col = self.SEL_PRIM_COLOR
                spr.box(self.canvas, x, col)
            x = nx
        if rs != RenderState.IMAGE:
            for vp in self.viewports:
                vp.draw(self.canvas, vp in self.selection)
        if self.grid_fore:
            self.render_grid()
        if rs != RenderState.IMAGE:
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
        for vp in self.viewports:
            if vp.contains(cpt):
                return vp
        for spr in self.sprites:
            if spr.contains(cpt):
                return spr
        return None

    @property
    def primary_selection(self):
        if not self.selection:
            return None
        return self.selection[0]

    def selection_is(self, kind):
        return isinstance(self.primary_selection, kind)

    def selection_has(self, kind):
        return any(isinstance(sel, kind) for sel in self.selection)

    def each_selected(self, kind):
        for sel in self.selection:
            if isinstance(sel, kind):
                yield sel

    def set_selection(self, obj):
        self.selection = [obj]

    def add_selection(self, obj):
        self.remove_selection(obj)
        self.selection.insert(obj, 0)

    def remove_selection(self, obj):
        while obj in self.selection:
            self.selection.remove(obj)

    def unselect(self):
        self.selection = []

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
            self.canvas.unmap_point(Vec2(0, self.canvas.view_size.y - 12)),
            self.HUD_COLOR,
            anchor_y = 'top',
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
        if self.selection_is(Sprite):
            spr = self.primary_selection
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
                f'Path: {spr.path}',
                f'Name: {spr.name}',
                f'Scale: {spr.scale:.3f}',
                f'Y-offset: {spr.y:.3f}',
                f'Rendered X: {spr.lastx:.3f}',
                f'Overlap: {spr.olap:.3f}',
                f'Pixel Size: {sw:.3f},{sh:.3f}',
                f'Ref: {ref}',
            ])
        elif self.selection_is(Viewport):
            vp = self.primary_selection
            rs = vp.render_size
            lines.extend([
                f'Name: {vp.name}',
                f'Origin: {vp.rect.x},{vp.rect.y} px',
                f'Real Size: {vp.rect.w} x {vp.rect.h} px',
                f'Render Size: {rs.x} x {rs.y} px',
                f'Scale: {vp.scale}',
            ])

        cw = self.canvas.view_size.x
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
        self.mods = mod | mod_for(key)
        self.keystate(Event(
            type=pygame.KEYDOWN,
            key=key,
            mod=mod,
        ))

    def ev_key_release(self, key, mod):
        self.mods = mod & ~mod_for(key)
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
        if (not self.selection) and self.sprites:
            if ds > 0:
                self.set_selection(self.sprites[0])
            else:
                self.set_selection(self.sprites[-1])
            return
        try:
            index = self.sprites.index(self.primary_selection)
        except ValueError:
            return
        place = index + ds
        if place < 0 or place >= len(self.sprites):
            return
        self.set_selection(self.sprites[place])

    def add_to_buffer(self, ev):
        pass

    def bump_sprite(self, spr, dx):
        try:
            index = self.sprites.index(spr)
        except ValueError:
            return
        place = index + dx
        if place < 0:
            place = 0
        if place > len(self.sprites):
            place = len(self.sprites)
        del self.sprites[index]
        self.sprites.insert(place, spr)

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
                    if self.selection_has(Sprite):
                        for spr in self.each_selected(Sprite):
                            self.bump_sprite(spr, -1)
            elif ev.key == key.RIGHT:
                if ev.mod == 0:
                    self.canvas.move(dx=0.1 * self.canvas.viewbox.w)
                elif ev.mod & key.MOD_ALT:
                    self.sel_offset(1)
                elif ev.mod & key.MOD_ACCEL:
                    if self.selection_has(Sprite):
                        for spr in self.each_selected(Sprite):
                            self.bump_sprite(spr, 1)
            elif ev.key == key.G:
                self.grid_fore = True
            elif ev.key == key.R:
                self.real_units = not self.real_units
            elif ev.key == key.K:
                if self.selection_has(Viewport):
                    source = list(self.each_selected(Viewport))
                    plural = 's' if len(source) > 1 else ''
                    msg = f'Rendered {len(source)} viewport{plural} in {{}}s'
                else:
                    source = self.viewports
                    msg = f'Rendered all viewports in {{}}s'
                start = time.perf_counter()
                for vp in source:
                    vp.render(self)
                end = time.perf_counter()
                self.message = msg.format(f'{end - start:.3f}')
            elif ev.key == key.Z:
                if self.selection_has(Sprite):
                    self.keystate = self.ks_reference
                elif self.selection_is(Viewport):
                    self.keystate = self.ks_vp_opposite
                    r = self.primary_selection.rect
                    self.undo_state = Vec2(r.w, r.h)
            elif ev.key == key.T:
                if self.selection_has(Sprite):
                    self.origmy = self.mpos.y
                    self.keystate = self.ks_move
                    self.undo_state = [spr.y for spr in self.each_selected(Sprite)]
                elif self.selection_is(Viewport):
                    self.keystate = self.ks_vp_origin
                    r = self.primary_selection.rect
                    self.undo_state = Vec2(r.x, r.y)
            elif ev.key == key.S:
                if self.selection_has(Sprite):
                    self.origmy = self.mpos.y
                    self.keystate = self.ks_scale
                    self.undo_state = [spr.scale for spr in self.each_selected(Sprite)]
                elif self.selection_has(Viewport):
                    self.origmy = self.mpos.y
                    self.keystate = self.ks_vp_scale
                    self.undo_state = [vp.scale for vp in self.each_selected(Viewport)]
            elif ev.key == key.O and self.selection_is(Sprite):
                idx = self.sprites.index(self.primary_selection)
                if idx > 0:
                    self.osprite = self.sprites[idx - 1]
                    self.origmx = self.mpos.x
                    self.keystate = self.ks_offset
                    self.undo_state = self.osprite.olap
                else:
                    self.message = "Can't offset the first sprite"
            elif ev.key == key.D and self.selection is not None:
                self.message = 'Really delete? (y/n)'
                self.keystate = self.ks_delete
            elif ev.key == key.V:
                self.keystate = self.ks_viewport
                self.origin = None
                self.work_vp = None
                self.message = 'Click origin'
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
            elif ev.key == key.N and self.primary_selection is not None:
                self.buffer = ''
                self.capture = True
                self.message = f'Name: {CURSOR}'
                self.keystate = self.ks_object_name
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
                obj = self.hit_test(self.canvas.unmap_point(ev.pos))
                if ev.mod & key.MOD_ACCEL and obj is not None:
                    self.remove_selection(obj)
                elif ev.mod & key.MOD_SHIFT and obj is not None:
                    self.add_selection(obj)
                else:
                    if obj is None and ev.mod == 0:
                        self.unselect()
                    else:
                        self.set_selection(obj)
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            delta = self.drag_pos - ev.pos
            delta = self.canvas.unmap_scaled(delta)
            self.canvas.origin = self.drag_origin + delta

    def ks_reference(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                for spr in self.each_selected(Sprite):
                    spr.refy = None
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            p = self.canvas.unmap_point(ev.pos)
            for spr in self.each_selected(Sprite):
                spr.refy = (p.y - spr.y) / spr.scale
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_0:
                for spr in self.each_selected(Sprite):
                    spr.y = -spr.refy
                    spr.refy = None
                    self.keystate = self.ks_default

    def ks_move(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                for spr, oy in zip(self.each_selected(Sprite), self.undo_state):
                    spr.y = oy
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            d = self.canvas.unmap_scaled(Vec2(0, ev.pos.y - self.origmy))
            for spr, oy in zip(self.each_selected(Sprite), self.undo_state):
                spr.y = oy + d.y

    def ks_scale(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                for spr, sc in zip(self.each_selected(Sprite), self.undo_state):
                    spr.scale = sc
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            d = ev.pos.y - self.origmy
            self.origmy = ev.pos.y
            base = 1.01
            if self.mods & key.MOD_ACCEL:
                base = 1.001
            elif self.mods & key.MOD_SHIFT:
                base = 1.1
            for spr in self.each_selected(Sprite):
                spr.scale *= base**d
            #print(f'new scale: {spr.scale}')

    def ks_vp_opposite(self, ev):
        vp = self.primary_selection
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                vp.rect.w, vp.rect.x = self.undo_state
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            cpt = self.canvas.unmap_point(ev.pos)
            vp.rect.w = cpt.x - vp.rect.x
            vp.rect.h = cpt.y - vp.rect.y

    def ks_vp_origin(self, ev):
        vp = self.primary_selection
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                vp.rect.x, vp.rect.y = self.undo_state
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            cpt = self.canvas.unmap_point(ev.pos)
            vp.rect.x, vp.rect.y = cpt.x, cpt.y

    def ks_vp_scale(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                for vp, sc in zip(self.each_selected(Viewport), self.undo_state):
                    vp.scale = sc
            self.keystate = self.ks_default
        elif ev.type == pygame.MOUSEMOTION:
            d = ev.pos.y - self.origmy
            self.origmy = ev.pos.y
            base = 1.01
            if self.mods & key.MOD_ACCEL:
                base = 1.001
            elif self.mods & key.MOD_SHIFT:
                base = 1.1
            for vp in self.each_selected(Viewport):
                vp.scale *= base**d

    def ks_offset(self, ev):
        spr = self.osprite
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                spr.olap = self.undo_state
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
                    if self.selection_is(Sprite):
                        try:
                            self.sprites.insert(
                                self.sprites.index(self.primary_selection),
                                spr,
                            )
                        except ValueError:
                            self.sprites.append(spr)
                    else:
                        self.sprites.append(spr)
                    self.set_selection(spr)
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
        self.message = f'Load: {self.buffer}{CURSOR}'

    def ks_delete(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == key.Y:
                if self.selection_is(Sprite):
                    self.sprites.remove(self.primary_selection)
                elif self.selection_is(Viewport):
                    self.viewports.remove(self.primary_selection)
                self.unselect()
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
        self.message = f'Write: {self.buffer}{CURSOR}'

    def ks_viewport(self, ev):
        if ev.type == pygame.MOUSEMOTION:
            cpt = self.canvas.unmap_point(ev.pos)
            if self.origin is not None:
                r = self.work_vp.rect
                r.w, r.h = cpt.x - r.x, cpt.y - r.y
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == mouse.RIGHT:
                if self.work_vp is not None:
                    self.viewports.remove(self.work_vp)
                self.keystate = self.ks_default
            elif ev.button == mouse.LEFT:
                cpt = self.canvas.unmap_point(ev.pos)
                if self.origin is None:
                    self.origin = cpt
                    self.work_vp = Viewport('unnamed', Rect(cpt.x, cpt.y, 1, 1))
                    self.viewports.append(self.work_vp)
                    self.message = 'Click opposite'
                else:
                    self.capture = True
                    self.set_selection(self.work_vp)
                    self.keystate = self.ks_object_name
                    self.buffer = ''
                    self.message = f'Name: {CURSOR}'

    def ks_object_name(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == key.ENTER:
                self.primary_selection.name = self.buffer
                self.keystate = self.ks_default
                self.capture = False
                self.message = ''
                return
        self.message = f'Name: {self.buffer}{CURSOR}'

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
