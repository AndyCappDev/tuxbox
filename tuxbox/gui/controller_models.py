"""Physical controls in display order for each supported controller model."""

ELITE_CONTROLS = (
    'side', 'top', 'tall', 'short',
    'c1', 'c2', 'tour',
    'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right',
    'scroll_up', 'scroll_down', 'scroll_click',
    'knob_cw', 'knob_ccw', 'knob_click',
    'dial_cw', 'dial_ccw', 'dial_click',
)

LITE_CONTROLS = (
    'top', 'tall', 'short', 'c1', 'c2', 'tour',
    'scroll_up', 'scroll_down', 'scroll_click',
    'knob_cw', 'knob_ccw', 'knob_click',
)


def get_model_controls(model: str) -> tuple:
    """Return the model's controls, using Elite for unknown model names."""
    return LITE_CONTROLS if model == 'lite' else ELITE_CONTROLS
