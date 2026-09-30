local e = eyesy
return {
  api_version = 1,
  setup = function(ctx)
    e.param("size", 0.5, 0.05, 1, 1)
    e.param("hue", 0.5, 0, 1, 4)
  end,
  draw = function(ctx)
    if ctx.auto_clear then
      e.clear(0.025, 0.035, 0.06)
    else
      -- Persist on: decay the previous frame instead of wiping it.
      e.color(0.025, 0.035, 0.06, 0.08)
      e.rect(0, 0, ctx.width, ctx.height)
    end
    e.color(e.palette(ctx.params.hue))
    e.circle(ctx.width / 2, ctx.height / 2,
      30 + ctx.params.size * 180 + ctx.audio.rms_left * 80)
    e.color(1, 1, 1)
    e.text("Your next mode starts here", 32, 48)
  end
}
