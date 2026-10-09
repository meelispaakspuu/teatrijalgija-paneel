# Teatrijälgija – juhtpaneel

Streamliti juhtpaneel privaatse repo `meelispaakspuu/teatrijalgija` jaoks.
Selles repos on **ainult paneeli kood**. Seaded, olek ja jälgija elavad privaatses repos;
paneel loeb ja muudab neid GitHubi API kaudu tokeniga, mis on Streamliti secrets'is.

Streamlit Community Cloud:
- Repository: `meelispaakspuu/teatrijalgija-paneel`, Branch: `main`, Main file: `app/streamlit_app.py`
- Secrets:
  ```toml
  GH_TOKEN = "github_pat_..."          # fine-grained: ainult teatrijalgija, Contents + Actions + Workflows RW
  GH_REPO = "meelispaakspuu/teatrijalgija"
  APP_PASSWORD = "..."
  ```

Paneeli koodi lähtekoht on `teatrijalgija` repo kaust `app/`; muudatused tehakse seal ja kopeeritakse siia.
