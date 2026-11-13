"""Generated music and sound effects (numpy only, no audio files, no network)."""

SAMPLE_RATE = 48000
SYNTH_VERSION = 1       # bump when the sound of anything changes: it is part of every cache key
BED_PEAK = 0.5          # rendered bed peak, -6 dBFS
SFX_PEAK = 0.5
LIMIT = 0.95            # the final mix never goes beyond this
BED_VOLUME = 0.5        # default bed volume
SFX_VOLUME = 0.7        # default clip volume
SFX_OVER_VOICE_MAX = 0.35
SFX_MIN_GAP = 0.4
SFX_MAX_PER_SCENE = 3
