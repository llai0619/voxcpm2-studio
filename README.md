# VoxCPM2 Studio

以 FastAPI 與原生 HTML 製作的 VoxCPM2 操作介面，提供聲音設計、可控聲音複製及極致複製。

## 在 172.16.0.103 啟動

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
