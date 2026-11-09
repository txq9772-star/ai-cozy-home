// 户外找路：在场地上铺一张网格，绕开设施。
// 目标位置本身在设施上（比如秋千座位），所以先走到旁边，最后一小步才上去。
const CELL = 0.4;
const CLEAR = 0.3;      // 人的半宽

// [x 半宽, z 起点, z 终点]，相对家具中心
function footprint(f) {
  switch (f.type) {
    case 'swing': return [2.3, -0.9, 0.9];
    case 'seesaw': return [2.0, -0.3, 0.3];
    case 'slide': return [0.8, -2.2, 2.0];
    case 'carousel': return [1.9, -1.9, 1.9];
    case 'sandbox': return [(f.w || 4) / 2, -(f.d || 3.2) / 2, (f.d || 3.2) / 2];
    case 'bench': return [(f.w || 2.2) / 2, -0.35, 0.3];
    case 'lamp_post': return [0.12, -0.12, 0.12];
    case 'lake': return [(f.w || 22) / 2 * 1.16 + 0.7, -(f.d || 12) / 2 - 0.3, (f.d || 12) / 2 * 1.16 + 0.7];
    case 'tree_big': return [0.4, -0.4, 0.4];
    case 'flowerbed': return [(f.w || 2) / 2, -(f.d || 0.8) / 2, (f.d || 0.8) / 2];
    case 'bed': case 'sofa': case 'table': case 'coffee_table': case 'desk': case 'cabinet': case 'fridge': case 'counter': case 'shelf': case 'bookshelf':
      return [(f.w || 1.6) / 2, -(f.d || 0.8) / 2, (f.d || 0.8) / 2];
    case 'armchair': return [0.55, -0.48, 0.48];
    case 'tv': return [(f.w || 2.4) / 2, -0.25, 0.25];
    case 'piano': return [1.0, -0.3, 1.2];
    case 'easel': return [0.45, -0.45, 0.25];
    case 'chess': return [0.45, -0.45, 0.45];
    case 'plant': case 'lamp': return [0.22, -0.22, 0.22];
    case 'beanbag': return [0.55, -0.55, 0.55];
    case 'chair': return [0.24, -0.24, 0.24];
    case 'boxes': return [0.9, -0.8, 0.9];
    default: return null;
  }
}

export function obstacles(room) {
  const out = [];
  for (const f of room.furniture || []) {
    const b = footprint(f);
    if (!b) continue;
    const [hx, z0, z1] = b;
    const turned = Math.abs((f.rot || 0) % 180) === 90 || f.face === 'e' || f.face === 'w';
    out.push(turned ? [f.x + z0, f.z - hx, f.x + z1, f.z + hx] : [f.x - hx, f.z + z0, f.x + hx, f.z + z1]);
  }
  return out;
}

export class Grid {
  constructor(room) {
    [this.x0, this.z0, this.x1, this.z1] = room.rect;
    this.w = Math.ceil((this.x1 - this.x0) / CELL);
    this.h = Math.ceil((this.z1 - this.z0) / CELL);
    this.rects = obstacles(room);
    this.parts = room.parts || null;
    this.blocked = new Uint8Array(this.w * this.h);
    for (let j = 0; j < this.h; j++) {
      for (let i = 0; i < this.w; i++) {
        const [x, z] = this.pos(i, j);
        if (this.hits(x, z)) this.blocked[j * this.w + i] = 1;
      }
    }
  }

  pos(i, j) { return [this.x0 + (i + 0.5) * CELL, this.z0 + (j + 0.5) * CELL]; }

  hits(x, z, pad = CLEAR) {
    if (this.parts) {               // 人的四角都要在走廊里，这样几段走廊的接缝是通的
      const inside = (a, b) => this.parts.some((p) => a > p[0] && a < p[2] && b > p[1] && b < p[3]);
      if (!(inside(x - 0.25, z - 0.25) && inside(x + 0.25, z - 0.25) && inside(x - 0.25, z + 0.25) && inside(x + 0.25, z + 0.25))) return true;
    }
    return this.rects.some((r) => x > r[0] - pad && x < r[2] + pad && z > r[1] - pad && z < r[3] + pad);
  }

  free(i, j) { return i >= 0 && j >= 0 && i < this.w && j < this.h && !this.blocked[j * this.w + i]; }

  cell(x, z) {
    return [Math.max(0, Math.min(this.w - 1, Math.floor((x - this.x0) / CELL))),
      Math.max(0, Math.min(this.h - 1, Math.floor((z - this.z0) / CELL)))];
  }

  // 离 (x, z) 最近的空格子
  nearest(x, z) {
    const [ci, cj] = this.cell(x, z);
    if (this.free(ci, cj)) return [ci, cj];
    let best = null, bd = Infinity;
    for (let j = 0; j < this.h; j++) {
      for (let i = 0; i < this.w; i++) {
        if (!this.free(i, j)) continue;
        const [px, pz] = this.pos(i, j), d = (px - x) ** 2 + (pz - z) ** 2;
        if (d < bd) { bd = d; best = [i, j]; }
      }
    }
    return best;
  }

  // 离 (x, z) 不太远的随便一个空地方
  randomNear(x, z, radius) {
    for (let n = 0; n < 40; n++) {
      const i = Math.floor(Math.random() * this.w), j = Math.floor(Math.random() * this.h);
      if (!this.free(i, j)) continue;
      const p = this.pos(i, j);
      if (Math.hypot(p[0] - x, p[1] - z) <= radius && p[0] > this.x0 + 0.5 && p[0] < this.x1 - 0.5 && p[1] > this.z0 + 0.5 && p[1] < this.z1 - 0.5) return p;
    }
    return null;
  }

  clearLine(a, b) {
    const n = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / (CELL / 2));
    for (let k = 0; k <= n; k++) {
      if (this.hits(a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n, CLEAR - 0.05)) return false;
    }
    return true;
  }

  // A*，返回 from 之后的路点，最后一个是 to
  find(from, to) {
    if (this.clearLine(from, to)) return [to];
    const s = this.nearest(from[0], from[1]), g = this.nearest(to[0], to[1]);
    if (!s || !g) return [to];
    const key = (i, j) => j * this.w + i;
    const start = key(s[0], s[1]), goal = key(g[0], g[1]);
    const gs = new Float32Array(this.w * this.h).fill(Infinity);
    const prev = new Int32Array(this.w * this.h).fill(-1);
    const shut = new Uint8Array(this.w * this.h);
    const heur = (i, j) => Math.hypot(i - g[0], j - g[1]);
    const open = [[heur(s[0], s[1]), start]];
    gs[start] = 0;
    while (open.length) {
      let m = 0;
      for (let k = 1; k < open.length; k++) if (open[k][0] < open[m][0]) m = k;
      const [, cur] = open.splice(m, 1)[0];
      if (cur === goal) break;
      if (shut[cur]) continue;
      shut[cur] = 1;
      const ci = cur % this.w, cj = (cur - ci) / this.w;
      for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
        const ni = ci + di, nj = cj + dj;
        if (!this.free(ni, nj) || (di && dj && (!this.free(ci + di, cj) || !this.free(ci, cj + dj)))) continue;
        const nk = key(ni, nj), d = gs[cur] + Math.hypot(di, dj);
        if (d < gs[nk]) { gs[nk] = d; prev[nk] = cur; open.push([d + heur(ni, nj), nk]); }
      }
    }
    if (goal !== start && prev[goal] < 0) return [to];
    const cells = [];
    for (let c = goal; c >= 0; c = prev[c]) cells.unshift(this.pos(c % this.w, (c - (c % this.w)) / this.w));
    const out = [];              // 能直走就不拐弯
    let at = cells[0];
    if (!this.clearLine(from, at)) out.push(at);
    let i = 0;
    while (i < cells.length - 1) {
      let j = cells.length - 1;
      while (j > i + 1 && !this.clearLine(cells[i], cells[j])) j--;
      out.push(cells[j]);
      i = j;
    }
    at = out[out.length - 1];
    out.push(to);
    return out;
  }
}
