# VoxCPM2 Studio

以 FastAPI 與原生 HTML 製作的 VoxCPM2 操作介面，提供聲音設計、可控聲音複製及極致複製。

## 在 172.16.0.103 啟動

### Windows 一鍵啟動（建議）

下載或 clone 本專案後，直接雙擊 `start-voxcpm2.bat`。它會：

1. 建立到 `llai@172.16.0.103` 的 SSH tunnel。
2. 更新伺服器上的專案。
3. 使用 `/home/llai/miniforge3/envs/voxcpm2/bin/python3.11`。
4. 檢查相依套件、啟動服務並開啟瀏覽器。

依畫面輸入 SSH 密碼，並在使用期間保持 BAT 視窗開啟。按 `Ctrl+C` 可停止服務。

若要自動登入，將 `.env.example` 複製成 `.env`，填入：

```dotenv
VOXCPM_SSH_PASSWORD=你的伺服器密碼
```

`.env` 已被 Git 忽略，不會推送至儲存庫。它仍是本機明文檔案，請勿分享；正式環境建議改用 SSH 金鑰。

如果 `.env` 不存在或密碼為空，BAT 第一次啟動時會安全提示輸入一次，然後自動建立 `.env`；輸入內容不會顯示在畫面上。

第一次使用前，伺服器需已有專案：

```bash
cd ~
git clone https://github.com/llai0619/voxcpm2-studio.git
```

### 手動啟動

先進入已安裝 VoxCPM2 的 Python/Conda 環境，再安裝 Web 端相依套件：

```bash
cd ~/voxcpm2-studio
python -m pip install -r requirements-web.txt
python server.py --host 127.0.0.1 --port 8808
```

模型預設為 `openbmb/VoxCPM2`、裝置為 `auto`。若模型已下載至特定目錄：

```bash
export VOXCPM_MODEL=/path/to/VoxCPM2
export VOXCPM_DEVICE=cuda:0
python server.py --host 127.0.0.1 --port 8808
```

從 Windows 建立安全的 SSH tunnel：

```powershell
ssh -L 8808:127.0.0.1:8808 llai@172.16.0.103
```

然後開啟 <http://127.0.0.1:8808>。若要在內網直接存取，可改用 `--host 0.0.0.0`，並確認伺服器防火牆設定。

## API

- `GET /api/status`：伺服器及模型狀態
- `POST /api/generate`：建立 WAV
- `GET /api/audio/{filename}`：播放或下載結果

產生的音檔位於 `outputs/`。可用 `VOXCPM_OUTPUT_DIR` 指定其他位置。
