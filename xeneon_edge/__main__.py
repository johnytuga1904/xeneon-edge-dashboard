# Vor dem ersten GTK-Import: GTK4 oeffnet EGL beim Start, und die
# Vendor-Wahl (webkit_env) muss davor im Environment stehen.
from . import webkit_env
webkit_env.apply()

from .app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
