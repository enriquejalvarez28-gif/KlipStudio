import { Config } from '@remotion/cli/config';

// On your PC nothing is needed: Remotion downloads its own browser.
// In a cloud session: export CHROME_PATH=/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell
if (process.env.CHROME_PATH) Config.setBrowserExecutable(process.env.CHROME_PATH);
