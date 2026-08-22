import { CommonModule } from '@angular/common';
import { Component, computed, input } from '@angular/core';

import { SkillAxis } from '../core/models';

interface Point {
  x: number;
  y: number;
}

interface AxisView {
  label: string;
  labelPos: Point;
  anchor: 'start' | 'middle' | 'end';
  spoke: Point;
  required: number;
  candidate: number;
}

/**
 * Hand-rolled SVG radar. A charting library would add ~100kB and a licence to
 * track for two polygons, and this needs no runtime dependency at all.
 */
@Component({
  selector: 'app-radar-chart',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (axes().length >= 3) {
      <svg
        [attr.viewBox]="'0 0 ' + size + ' ' + size"
        class="radar"
        role="img"
        [attr.aria-label]="ariaLabel()"
      >
        <!-- concentric guide rings -->
        @for (ring of rings; track ring) {
          <polygon [attr.points]="ringPoints(ring)" class="ring" />
        }
        @for (axis of view(); track axis.label) {
          <line [attr.x1]="center" [attr.y1]="center" [attr.x2]="axis.spoke.x" [attr.y2]="axis.spoke.y" class="spoke" />
        }

        <polygon [attr.points]="requiredPolygon()" class="required" />
        <polygon [attr.points]="candidatePolygon()" class="candidate" />

        @for (axis of view(); track axis.label) {
          <circle [attr.cx]="pointFor(axis, axis.candidate).x" [attr.cy]="pointFor(axis, axis.candidate).y" r="3.5" class="dot" />
          <text
            [attr.x]="axis.labelPos.x"
            [attr.y]="axis.labelPos.y"
            [attr.text-anchor]="axis.anchor"
            class="label"
          >
            {{ axis.label }}
          </text>
        }
      </svg>

      <div class="legend">
        <span class="key"><i class="swatch req"></i>Role demands</span>
        <span class="key"><i class="swatch cand"></i>Candidate coverage</span>
      </div>
    } @else {
      <!-- Fewer than 3 axes cannot form a polygon, so fall back to bars. -->
      <div class="bars">
        @for (axis of axes(); track axis.axis) {
          <div class="bar-row">
            <span class="bar-label">{{ axis.axis }}</span>
            <div class="track">
              <div class="fill req" [style.width.%]="axis.required"></div>
              <div class="fill cand" [style.width.%]="axis.candidate"></div>
            </div>
            <span class="bar-val">{{ axis.candidate }}/{{ axis.required }}</span>
          </div>
        }
      </div>
    }
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .radar {
        width: 100%;
        max-width: 380px;
        height: auto;
        margin: 0 auto;
        display: block;
        overflow: visible;
      }
      .ring {
        fill: none;
        stroke: var(--border);
        stroke-width: 1;
      }
      .spoke {
        stroke: var(--border);
        stroke-width: 1;
      }
      .required {
        fill: color-mix(in srgb, var(--muted-fg) 14%, transparent);
        stroke: var(--muted-fg);
        stroke-width: 1.5;
        stroke-dasharray: 4 3;
      }
      .candidate {
        fill: color-mix(in srgb, var(--accent) 26%, transparent);
        stroke: var(--accent);
        stroke-width: 2;
      }
      .dot {
        fill: var(--accent);
      }
      .label {
        fill: var(--muted-fg);
        font-size: 11px;
        font-weight: 500;
      }
      .legend {
        display: flex;
        gap: 1.25rem;
        justify-content: center;
        margin-top: 0.75rem;
        font-size: 0.8rem;
        color: var(--muted-fg);
      }
      .key {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
      }
      .swatch {
        width: 12px;
        height: 12px;
        border-radius: 3px;
        display: inline-block;
      }
      .swatch.req {
        background: color-mix(in srgb, var(--muted-fg) 30%, transparent);
        border: 1.5px dashed var(--muted-fg);
      }
      .swatch.cand {
        background: color-mix(in srgb, var(--accent) 40%, transparent);
        border: 1.5px solid var(--accent);
      }
      .bars {
        display: grid;
        gap: 0.6rem;
      }
      .bar-row {
        display: grid;
        grid-template-columns: 8rem 1fr 4rem;
        gap: 0.6rem;
        align-items: center;
        font-size: 0.85rem;
      }
      .track {
        position: relative;
        height: 10px;
        background: var(--surface-2);
        border-radius: 999px;
        overflow: hidden;
      }
      .fill {
        position: absolute;
        inset-block: 0;
        left: 0;
        border-radius: 999px;
      }
      .fill.req {
        background: color-mix(in srgb, var(--muted-fg) 30%, transparent);
      }
      .fill.cand {
        background: var(--accent);
        height: 5px;
        top: 2.5px;
      }
      .bar-val {
        text-align: right;
        color: var(--muted-fg);
        font-variant-numeric: tabular-nums;
      }
    `,
  ],
})
export class RadarChart {
  readonly axes = input.required<SkillAxis[]>();

  readonly size = 320;
  readonly center = 160;
  readonly radius = 108;
  readonly rings = [0.25, 0.5, 0.75, 1];

  /** Start at 12 o'clock and walk clockwise. */
  private angle(i: number, total: number): number {
    return (2 * Math.PI * i) / total - Math.PI / 2;
  }

  private at(i: number, total: number, value: number): Point {
    const a = this.angle(i, total);
    const r = (this.radius * Math.max(0, Math.min(100, value))) / 100;
    return { x: this.center + r * Math.cos(a), y: this.center + r * Math.sin(a) };
  }

  readonly view = computed<AxisView[]>(() => {
    const list = this.axes();
    return list.map((axis, i) => {
      const a = this.angle(i, list.length);
      const lx = this.center + (this.radius + 22) * Math.cos(a);
      const ly = this.center + (this.radius + 22) * Math.sin(a);
      const cos = Math.cos(a);
      // Nudge labels away from the polygon so they never overlap the spokes.
      const anchor: 'start' | 'middle' | 'end' =
        Math.abs(cos) < 0.25 ? 'middle' : cos > 0 ? 'start' : 'end';
      return {
        label: axis.axis,
        labelPos: { x: lx, y: ly + 4 },
        anchor,
        spoke: this.at(i, list.length, 100),
        required: axis.required,
        candidate: axis.candidate,
      };
    });
  });

  readonly ariaLabel = computed(() =>
    this.axes()
      .map((a) => `${a.axis}: candidate ${a.candidate} of ${a.required} required`)
      .join('. '),
  );

  pointFor(axis: AxisView, value: number): Point {
    const list = this.view();
    return this.at(list.indexOf(axis), list.length, value);
  }

  ringPoints(scale: number): string {
    const list = this.axes();
    return list.map((_, i) => this.fmt(this.at(i, list.length, scale * 100))).join(' ');
  }

  requiredPolygon(): string {
    const list = this.axes();
    return list.map((a, i) => this.fmt(this.at(i, list.length, a.required))).join(' ');
  }

  candidatePolygon(): string {
    const list = this.axes();
    return list.map((a, i) => this.fmt(this.at(i, list.length, a.candidate))).join(' ');
  }

  private fmt(p: Point): string {
    return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
  }
}
