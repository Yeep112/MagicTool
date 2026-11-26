# Magic Tool 實驗分析

把原本 Magic Tool notebook 裡的 PPMS、SQUID、Raman、Etching Rate 分析整理成一個軟體：雙擊開啟、選檔案、調參數，圖馬上更新。
分析程式和 notebook 共用（`magic/`），軟體與 Jupyter 算出來的結果完全一樣。

```
MagicTool\
├─ install.bat          ← 第一次雙擊：建立開始功能表與桌面捷徑
├─ run_magic.bat        ← 開啟軟體（可以複製到任何地方；把檔案或資料夾拖上去會直接開啟）
├─ MagicTool.pyw        ← 直接開啟軟體（工作列釘選的圖示執行的就是它）
├─ publish.bat          ← 開發者：一鍵發佈到 GitHub（同事會收到更新）
├─ magic_env.bat        ← 尋找電腦上的 Python（給上面的啟動檔用）
├─ release.json         ← 版本號與更新內容（版本號只寫在這裡）
├─ 發佈與更新.md         ← 第一次上傳 GitHub、之後每次發佈的步驟
├─ magic\               ← 程式本體（Python 原始檔，可以直接改）
│   ├─ core\            共用：設定、單位、欄位搜尋、掃描分段、Tc、峰擬合、分析登錄、結果匯出
│   ├─ readers\         讀檔：QD .dat（PPMS + SQUID 共用）、Raman 文字檔
│   ├─ ppms\  squid\  raman\  etching\     ← 每台機台一個資料夾，一個分析一個檔案
│   └─ gui\             軟體介面
├─ notebooks\           ← 四台機台的 notebook（呼叫 magic\ 的同一份程式；上傳前自動清掉輸出）
├─ tests\               ← pytest（只用合成資料）
└─ assets\              ← 圖示
```

需要：Anaconda（numpy、scipy、pandas、matplotlib、tkinter 都內建）。Google Sheet 同步另外需要 `pip install gspread google-auth`。

## 第一次使用

1. 把整個資料夾放在固定位置，例如 `D:\Yeep\MagicTool\`（不要在 zip 裡直接執行）。
2. 雙擊 **`install.bat`**（只要一次）：「開始」功能表和桌面會出現「Magic Tool 實驗分析」。
3. 開啟後在每台機台按「選資料夾」；沒有資料想先試試看，按「先用範例資料試試看」（合成資料，不是真實量測）。
4. Etching：到 **⚙ 設定 → 蝕刻紀錄** 把「紀錄 CSV」指向原本的 `etch_rate_log.csv`（欄位相同，可以直接接著用）。

## 介面

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ ✦ Magic Tool  [PPMS][SQUID][Raman][Etching]                  📂輸出資料夾  ⚙設定 │
├──────────────┬───────────────────────────┬───────────────────────────────────────┤
│ 快速檢視      │ ☰ PPMS 資料      2 個檔案 │ R–T 與 Tc                    1 個檔案  │
│  ∿ 曲線檢視   │ [資料夾路徑] 選資料夾 選檔案│ 圖 [填滿視窗▼] 寬 高  格線  字體       │
│ 參數萃取      │ ⌕ 篩選                     │ 工具列（Home / 平移 / 放大 / 存檔）     │
│  Tc R–T 與 Tc │ 檔名     種類  大小  時間  │                                       │
│ 批次比較      │ …                          │      圖（滑鼠移上去顯示數值）           │
│  ≋ 多樣品比較 ├───────────────────────────┤                                       │
│               │ Tc R–T 與 Tc     恢復預設  │                                       │
│               │ 溫度欄位 [Temperature (K)▼]├───────────────────────────────────────┤
│               │ 溫度範圍 [        ]        │ ≡ 文字結果（Tc、峰位…；⚠ 提醒）  複製   │
│               │ [▶ 繪圖][存圖][匯出結果] ☑自動重畫                                  │
└──────────────┴───────────────────────────┴───────────────────────────────────────┘
```

- 上方切換機台（Ctrl+1～4），每台機台有自己的主色，各自記住資料夾、選的檔案、功能與參數。
- 左欄依**快速檢視 / 參數萃取 / 批次比較**分組。
- 中欄選檔案（Ctrl / Shift 多選、Ctrl+A 全選），「種類」欄會標出是 PPMS 還是 SQUID 的檔案（灰色 = 可能放錯機台）。
- 參數改了會自動重畫；格式不對的欄位會變紅框，不會當掉。滑鼠停在 ⓘ 上有說明。
- 圖的大小：「固定大小」可以自己設寬高，圖不會被壓縮，放不下就出現捲軸；「填滿視窗」時每個子圖也有最小尺寸。
- **存圖**（Ctrl+S）、**匯出結果**（Ctrl+E）：存到「輸出資料夾」（預設 `文件\MagicTool 輸出\<機台>\`），**不會寫進原始資料夾**。
  匯出結果會有 `figure.png`、表格 CSV、`result.txt` 和 `result.json`（來源檔的 SHA-256、參數、軟體版本），寫論文時可以重現。
- F5：重新計算。

## 分析功能

| 機台 | 快速檢視 | 參數萃取 | 批次比較 |
|---|---|---|---|
| PPMS | 曲線檢視（任選兩欄、自動分段） | R–T 與 Tc | 多樣品 R–T 比較 |
| SQUID | 曲線檢視（單位自動換算） | M–T 與 Tc（ZFC / FC）、M–H 迴線 | 多樣品 M–T 比較 |
| Raman | 光譜檢視（疊圖、正規化、扣背景） | 石墨烯 G / 2D 峰、背景扣除 | 多檔峰值總表 |
| Etching | 蝕刻速率趨勢 | （＋ 新增紀錄 表單） | 條件比較（平均 ± 標準差） |

**Tc**（PPMS、SQUID 共用 `magic/core/transition.py`）：先依掃描方向切段（降溫 / 升溫、ZFC / FC 分開），
正規化 f = (y − y_低溫) / (y_正常 − y_低溫)，從高溫往低溫找 90%、50%、10%，另外找平滑後 |dy/dT| 最大的溫度。
溫度範圍空白時自動選「最低溫到 2 × 轉變溫度」，避免 300 K 的正常態電阻把 Tc 算歪。

**Raman 峰**（`magic/core/peaks.py`）：只在指定範圍內找峰、Lorentzian 擬合求峰位 / FWHM / 高度 / 面積；
沒有明顯的峰（高度 < 5 倍雜訊、R² 太低）會回報「找不到」，不會硬給一個值。舊方法「平均強度交點寬度 Δ」也一起算，方便和以前的紀錄比較。

## 和原本 notebook / yeep_lab 的差別

| 以前的問題 | 現在 |
|---|---|
| 降溫、升溫混在一起排序，曲線來回跳；接縫處被誤判成斜率最大 | `core/segments.py` 先切段，每段分開分析 |
| SQUID Tc = 相鄰兩點斜率最大，溫度幾乎相同的兩點會得到假的極大值 | 內插到等間距格點、可平滑後再微分；50% / 90% / 10% 用正規化數值 |
| Raman 找「最靠近 1580 / 2700 的峰」、`distance` 單位是資料點 | 在範圍內找、Lorentzian 擬合 |
| 多項式背景被峰拉高 | 只用無峰區（ModPoly）、或 ALS |
| Raman cell 用到前一格的變數（legend、標籤錯） | 每個分析是獨立的函式，不會共用變數 |
| `read_qd_dat`：Comment 欄有一格像數字就整欄變 NaN | 九成以上是數字才轉換 |
| `[Header]` 只存原始文字 | 解析成 dict（BYAPP、INFO…），用來判斷 PPMS / SQUID |
| `find_col` 有好幾個符合時默默拿第一個 | 會在文字結果提醒（例如 Bridge 1 / 2 / 3） |
| Raman 讀檔遇到標題列、逗號分隔就失敗 | 自動略過標題、支援空白 / Tab / 逗號 / 分號，由大到小自動排序 |
| Etching：Δ_SiO2 正負號和計算相反；缺值 TypeError；負值默默改 0；重跑就重複寫入 | 統一成「被蝕刻掉的厚度」；說明缺哪一格；負值提醒；先預覽再寫入、重複會提醒 |
| CSV / xlsx / Google Sheet 三份資料 | 本機 CSV 是主要來源，Excel / Google Sheet 是選用的副本 |
| 結果 CSV 寫進原始資料夾 | 寫到輸出資料夾 |
| `paths.HOME` 依安裝方式推算、`ensure_dirs()` 在每台電腦建資料夾、金鑰放在可能同步的資料夾 | 設定、紀錄、金鑰都在 `%LOCALAPPDATA%\MagicTool\` |
| `pyproject.toml` 漏裝子套件、版本號寫兩次、jupyterlab 是必要套件 | `packages.find`；版本號只在 `release.json`；notebook 套件改成選用 |

## 新增分析功能

複製 `magic/ppms/_template.py`，改檔名（不要以 `_` 開頭）、改內容，重新開啟軟體就會出現在左欄：

```python
@analysis("PPMS", "我的分析", group="參數萃取", icon="★",
          params=[P("x", "X 軸", "Temperature (K)", kind="column"),
                  P("T_range", "溫度範圍", "2, 10", kind="range"),
                  P("smooth", "平滑點數", 0)])
def my_analysis(fig, items, p, data=None):
    ...                       # items[i].data.df 是 pandas DataFrame；p["T_range"] 已經轉成 (2.0, 10.0)
    return Result(text="…", tables={"summary": df})
```

- 參數面板依 `params` 自動產生：數字 → 輸入框、`True/False` → 勾選、`choices` → 下拉、`kind="column"` → 檔案的欄位、`kind="range"` → 「最小, 最大」。
- 慢的計算寫成 `compute=函式(items, p, progress)`，會在背景執行，介面不會卡住。
- 放在 `magic/<機台>/` → 跟著上傳 GitHub，同事也會收到。
- **私人的分析或機台**：放在 `%LOCALAPPDATA%\MagicTool\plugins\`（⚙ 設定 → 資料夾 有按鈕開啟），不會被上傳。
  新機台用 `register_instrument(Instrument(...))` 登錄，介面上方就會多一個分頁。

## 設定與紀錄放在哪裡

`%LOCALAPPDATA%\MagicTool\`（每台電腦各自一份，更新和上傳 GitHub 都不會碰到）：

| 檔案 | 內容 |
|---|---|
| `settings.toml` | 資料夾、輸出位置、蝕刻紀錄 CSV、Google Sheet（⚙ 設定 裡改，或用記事本） |
| `gui_state.json` | 上次的機台、資料夾、選的檔案、功能、參數、分隔線位置 |
| `secrets\service_account.json` | Google Sheet 金鑰（不要放在工具資料夾） |
| `etching\etch_rate_log.csv` | 沒指定位置時的蝕刻紀錄 |
| `logs\` | app.log、error.log、crash.log（出問題時貼給 Claude） |
| `plugins\` | 私人的分析功能 |

## 自我測試

```
run_magic.bat selftest        （publish.bat 上傳前會自動跑，沒通過就不上傳）
python -m pytest -q           （不含視窗的部分）
```

只用程式產生的合成資料，檢查：每個分析的數值和正確答案一致（Tc、峰位、FWHM、Hc）、讀檔、蝕刻速率、設定檔、
notebook 清除輸出、自動更新流程，以及軟體視窗（每個功能實際畫一次、切換機台的時間、背景計算時畫面不能卡住、固定大小的圖不被壓縮）。
