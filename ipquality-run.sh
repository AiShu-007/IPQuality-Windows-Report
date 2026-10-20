#!/usr/bin/env bash
# Portable adaptation, modified 2026-10-20. Copyright (C) 2026 sunzh815. AGPL-3.0.
cd -- "$(dirname -- "$0")"
export PATH="$PWD/ipquality-tools:$PATH"
export CURL_CA_BUNDLE="$(cygpath -w "$PWD/ipquality-tools/windows-trusted-ca.pem")"
export HTTP_PROXY="${IPQ_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY="$HTTP_PROXY"
export ALL_PROXY="$HTTP_PROXY"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTP_PROXY"
export NO_PROXY="127.0.0.1,localhost"
export TERM=xterm
python_bin="${IPQ_PYTHON:-python}"
[[ "$python_bin" =~ ^[A-Za-z]: ]] && python_bin="$(cygpath -u "$python_bin")"
if ! "$python_bin" -c 'from PIL import Image, ImageDraw, ImageFont' >/dev/null 2>&1; then
  echo 'Python with Pillow is required for PNG reports. Install it with: python -m pip install Pillow' >&2
  exit 2
fi
# Load the upstream functions without its platform-specific entry point.
# The upstream file is retained unchanged for comparison and updates.
# Correct upstream's JSON-only IPQS key typo while loading; the downloaded
# original file remains unchanged, and terminal/PNG scores stay intact.
source <(sed -e '/^generate_random_user_agent$/,$d' \
  -e 's/${ipapi\[ipqs\]:-null}/${ipqs[score]:-null}/g' ./ipquality-original.sh)

# These checks are unavailable through an HTTP proxy on this Windows host.
# Keep their values unknown rather than reporting success from missing tools.
get_ipv6() { IPV6=""; IPV6work=0; }
show_progress_bar() { :; }
kill_progress_bar() { :; }
show_ad() { ADLines=0; }
Get_Unlock_Type() { echo ""; }
Check_DNS_1() { echo ""; }
Check_DNS_2() { echo ""; }
Check_DNS_3() { echo ""; }
check_mail() {
  smail[local]=2
  smail[remote]=0
  services=(Gmail Outlook Yahoo Apple QQ MailRU AOL GMX MailCOM 163 Sohu Sina)
}
check_dnsbl() {
  smail[t]=null; smail[c]=null; smail[m]=null; smail[b]=null
}
show_mail() { printf '\nWindows compatibility: supplementary SMTP and DNS checks run after the core report; DNS unlock type is unavailable.\n'; }

generate_random_user_agent
adapt_locale
rawgithub="https://raw.githubusercontent.com/xykt/IPQuality/"
get_ipv4
is_valid_ipv4 "$IPV4"
get_opts -n -4 -p -f -x "$HTTP_PROXY" "$@"
set_language
if [[ $ERRORcode -ne 0 ]]; then
  echo "${swarn[$ERRORcode]}" >&2
  exit "$ERRORcode"
fi
if [[ ${mode_output:-0} -eq 0 ]]; then
  mkdir -p reports
  outputfile="reports/ipquality-$(date +%Y%m%d-%H%M%S)-$$.json"
  mode_output=1
fi
case "$outputfile" in
  *.json) report_prefix="${outputfile%.json}" ;;
  *)
    echo 'Use a .json output path; matching .ansi, .txt, and .png files are generated automatically.' >&2
    exit 2
    ;;
esac
if [[ -e "$report_prefix.png" || -e "$report_prefix.ansi" || -e "$report_prefix.txt" ]]; then
  echo 'A report with that name already exists. Choose another output path.' >&2
  exit 2
fi
# Capture colored terminal output; the JSON result is written by upstream -o.
mode_json=0
read_ref
ADLines=0
echo "[1/3] Core IP quality and service checks..." >&2
check_IP "$IPV4" 4 | tee "$report_prefix.raw.ansi"
# The upstream function may return 1 after writing a valid result. The renderer
# validates the JSON and matching IP before generating a new image.
if [[ ! -s "$outputfile" || ! -s "$report_prefix.raw.ansi" ]]; then
  echo 'Detection did not produce a complete result. No image was generated.' >&2
  exit 1
fi
echo "[2/3] Supplementary geolocation, SMTP and DNS checks..." >&2
if ! "$python_bin" -X utf8 ./supplement_ipquality.py --json "$outputfile" --proxy "$xproxy"; then
  echo 'Additional probes did not finish. Missing fields will remain explicitly unknown.' >&2
fi
render_args=(--input "$report_prefix.raw.ansi" --json "$outputfile" --output "$report_prefix.png" --proxy "$xproxy")
[[ ${IPQ_OPEN_REPORT:-0} == 1 ]] && render_args+=(--open)
echo "[3/3] Rendering PNG and complete text report..." >&2
if ! "$python_bin" -X utf8 ./render_ipquality_report.py "${render_args[@]}"; then
  echo 'Detection data was saved, but image generation failed.' >&2
  exit 2
fi
echo "JSON: $outputfile" >&2
echo "PNG:  $report_prefix.png" >&2
exit 0
