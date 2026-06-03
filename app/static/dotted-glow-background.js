class DottedGlowBackground {
  constructor(container, options = {}) {
    this.container = container;
    this.options = {
      gap: 14,
      radius: 1.7,
      color: "rgba(224,187,106,0.62)",
      glowColor: "rgba(224,187,106,0.9)",
      opacity: 0.68,
      speedMin: 0.35,
      speedMax: 1.15,
      speedScale: 1,
      ...options,
    };
    this.canvas = document.createElement("canvas");
    this.canvas.className = "dotted-glow-canvas";
    this.ctx = this.canvas.getContext("2d");
    this.dots = [];
    this.raf = 0;
    this.visible = true;
    this.stopped = false;
    this.lastSize = { width: 0, height: 0 };

    this.container.appendChild(this.canvas);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.visibilityObserver = new IntersectionObserver(
      (entries) => {
        this.visible = entries[0]?.isIntersecting ?? true;
      },
      { threshold: 0.1 },
    );
    this.resizeObserver.observe(this.container);
    this.visibilityObserver.observe(this.container);
    this.resize();
    this.raf = requestAnimationFrame((time) => this.draw(time));
  }

  resize() {
    const { width, height } = this.container.getBoundingClientRect();
    const dpr = Math.min(Math.max(1, window.devicePixelRatio || 1), 2);
    const nextWidth = Math.max(1, Math.floor(width));
    const nextHeight = Math.max(1, Math.floor(height));
    if (nextWidth === this.lastSize.width && nextHeight === this.lastSize.height) return;

    this.lastSize = { width: nextWidth, height: nextHeight };
    this.canvas.width = Math.floor(nextWidth * dpr);
    this.canvas.height = Math.floor(nextHeight * dpr);
    this.canvas.style.width = `${nextWidth}px`;
    this.canvas.style.height = `${nextHeight}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.regenerateDots(nextWidth, nextHeight);
  }

  regenerateDots(width, height) {
    const { gap, speedMin, speedMax } = this.options;
    const min = Math.min(speedMin, speedMax);
    const max = Math.max(speedMin, speedMax);
    const cols = Math.ceil(width / gap) + 2;
    const rows = Math.ceil(height / gap) + 2;
    this.dots = [];

    for (let col = -1; col < cols; col += 1) {
      for (let row = -1; row < rows; row += 1) {
        this.dots.push({
          x: col * gap + (row % 2 === 0 ? 0 : gap * 0.5),
          y: row * gap,
          phase: Math.random() * Math.PI * 2,
          speed: min + Math.random() * Math.max(max - min, 0),
        });
      }
    }
  }

  draw(now) {
    if (this.stopped) return;
    this.raf = requestAnimationFrame((time) => this.draw(time));
    if (!this.visible || !this.ctx) return;

    const { width, height } = this.lastSize;
    const { radius, color, glowColor, opacity, speedScale } = this.options;
    const time = (now / 1000) * Math.max(speedScale, 0);

    this.ctx.clearRect(0, 0, width, height);
    this.ctx.fillStyle = color;

    for (const dot of this.dots) {
      const wave = (time * dot.speed + dot.phase) % 2;
      const alpha = 0.22 + 0.58 * (wave < 1 ? wave : 2 - wave);
      const glow = Math.max(0, (alpha - 0.55) / 0.45);

      this.ctx.globalAlpha = alpha * opacity;
      this.ctx.shadowColor = glow > 0 ? glowColor : "transparent";
      this.ctx.shadowBlur = 7 * glow;
      this.ctx.beginPath();
      this.ctx.arc(dot.x, dot.y, radius, 0, Math.PI * 2);
      this.ctx.fill();
    }
  }

  destroy() {
    this.stopped = true;
    cancelAnimationFrame(this.raf);
    this.resizeObserver.disconnect();
    this.visibilityObserver.disconnect();
    this.canvas.remove();
  }
}

window.DottedGlowBackground = DottedGlowBackground;
