import streamlit as st
import pdfplumber
from streamlit_drawable_canvas import st_canvas
from PIL import Image, ImageDraw, ImageFont
import io
import img2pdf
import numpy as np
from rapidocr_onnxruntime import RapidOCR
from pptx import Presentation
from pptx.util import Inches
import os

# --- 1. 核心設定 ---
st.set_page_config(page_title="NotebookLM AI 旗艦版 (Canvas Fix)", layout="wide")

st.markdown("""
    <style>
    ::-webkit-scrollbar { width: 0px; background: transparent; }
    .block-container { padding-top: 3rem; padding-bottom: 5rem; }
    div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] { gap: 0px; }
    .nav-btn button {
        border-top-left-radius: 0 !important;
        border-top-right-radius: 0 !important;
        border-top: 0 !important;
        background-color: #f8f9fa;
        color: #333;
        font-weight: bold;
        transition: 0.2s;
    }
    .nav-btn button:hover {
        background-color: #e3f2fd !important;
        color: #0071e3 !important;
    }
    .thumb-box {
        border: 1px solid #ddd;
        border-bottom: 0;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        overflow: hidden;
    }
    div[data-testid="column"]:nth-of-type(3) {
        background-color: #1E1E1E;
        padding: 20px;
        border-radius: 16px;
        border: 1px solid #444;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }
    .stTextArea textarea, .stTextInput input, .stNumberInput input {
        color: #ffffff !important;
        background-color: #2D2D2D !important;
        border: 1px solid #555 !important;
    }
    .stSelectbox div[data-baseweb="select"] > div {
        background-color: #2D2D2D !important;
        color: white !important;
    }
    label, .stMarkdown p, .stCaption, .stCheckbox label { color: #e0e0e0 !important; }
    div[data-testid="column"]:nth-of-type(3) button p { color: #ffffff !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. 狀態管理 ---
if 'pages_data' not in st.session_state: st.session_state.pages_data = {} 
if 'history' not in st.session_state: st.session_state.history = {} 
if 'history_redo' not in st.session_state: st.session_state.history_redo = {} 
if 'ocr_results' not in st.session_state: st.session_state.ocr_results = {} 
if 'current_page' not in st.session_state: st.session_state.current_page = 0
if 'selected_index' not in st.session_state: st.session_state.selected_index = 0
if 'editing_text' not in st.session_state: st.session_state.editing_text = ""
if 'canvas_key' not in st.session_state: st.session_state.canvas_key = 0 

# --- 3. 載入 RapidOCR ---
@st.cache_resource
def get_ocr_engine():
    return RapidOCR(det_db_unclip_ratio=1.3) 

# 字體設定
FONT_DIR = "fonts"
FONT_PATH_NORMAL = os.path.join(FONT_DIR, "msjh.ttc")
FONT_PATH_BOLD = os.path.join(FONT_DIR, "msjhbd.ttc")

if not os.path.exists(FONT_PATH_BOLD): FONT_PATH_BOLD = FONT_PATH_NORMAL
if not os.path.exists(FONT_PATH_NORMAL): 
    FONT_PATH_NORMAL = None 
    FONT_PATH_BOLD = None

DISPLAY_WIDTH = 800 

# --- 關鍵修正：圖片清洗函數 ---
def sanitize_image(pil_image):
    """
    將圖片強制轉為 RGB 並重整記憶體，解決雲端畫布黑屏問題。
    """
    # 1. 強制轉 RGB
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    
    # 2. 存入記憶體再讀出 (像存檔一樣清洗資料)
    b = io.BytesIO()
    pil_image.save(b, format="PNG")
    b.seek(0)
    
    # 3. 回傳全新的乾淨圖片物件
    return Image.open(b)

# --- 歷史紀錄 ---
def save_history(page_idx, current_img_bytes):
    if page_idx not in st.session_state.history: st.session_state.history[page_idx] = []
    if len(st.session_state.history[page_idx]) > 10: st.session_state.history[page_idx].pop(0)
    st.session_state.history[page_idx].append(current_img_bytes)
    if page_idx in st.session_state.history_redo: st.session_state.history_redo[page_idx] = []

def perform_undo(page_idx):
    if page_idx in st.session_state.history and st.session_state.history[page_idx]:
        current_state = st.session_state.pages_data.get(page_idx)
        if current_state:
            if page_idx not in st.session_state.history_redo: st.session_state.history_redo[page_idx] = []
            st.session_state.history_redo[page_idx].append(current_state)
        st.session_state.pages_data[page_idx] = st.session_state.history[page_idx].pop()
        return True
    return False

def perform_redo(page_idx):
    if page_idx in st.session_state.history_redo and st.session_state.history_redo[page_idx]:
        current_state = st.session_state.pages_data.get(page_idx)
        if current_state: st.session_state.history[page_idx].append(current_state)
        st.session_state.pages_data[page_idx] = st.session_state.history_redo[page_idx].pop()
        return True
    return False

# --- 4. 主程式 ---
st.title("🤖 NotebookLM AI 旗艦版 (雲端畫布修復)")

uploaded_file = st.file_uploader("請上傳 PDF", type="pdf")

if uploaded_file:
    with pdfplumber.open(uploaded_file) as pdf:
        total_pages = len(pdf.pages)
        col_nav, col_canvas, col_edit = st.columns([1.2, 3.5, 1.5])

        # === 左側：目錄 ===
        with col_nav:
            st.subheader("📑 頁面")
            with st.container(height=700):
                for i in range(total_pages):
                    # 使用 sanitize_image 清洗
                    raw_thumb = pdf.pages[i].to_image(resolution=40).original
                    thumb = sanitize_image(raw_thumb)
                    
                    status_text = f"第 {i+1} 頁"
                    if i in st.session_state.pages_data:
                        status_text = f"✅ {i+1} (已修)"

                    st.markdown(f'<div class="thumb-box" style="border-bottom: 1px solid #ddd;">', unsafe_allow_html=True)
                    st.image(thumb, use_column_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)

                    btn_container = st.container()
                    with btn_container:
                        st.markdown('<div class="nav-btn">', unsafe_allow_html=True)
                        if st.button(status_text, key=f"nav_{i}", use_container_width=True):
                            st.session_state.current_page = i
                            st.session_state.selected_index = 0
                            st.session_state.editing_text = ""
                            st.session_state.canvas_key += 1
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                    st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        curr = st.session_state.current_page
        page = pdf.pages[curr]

        # === 中間：畫布 ===
        with col_canvas:
            st.subheader(f"📍 工作區 (第 {curr+1} 頁)")
            
            # 準備底圖 (關鍵修復點)
            if curr in st.session_state.pages_data:
                # 已經有修改過的圖，讀取並清洗
                raw_img = Image.open(io.BytesIO(st.session_state.pages_data[curr]))
                bg_img = sanitize_image(raw_img)
            else:
                # 原始 PDF 圖，讀取並清洗
                raw_img = page.to_image(resolution=150).original
                bg_img = sanitize_image(raw_img)

            # [狀態 A] 尚未分析
            if curr not in st.session_state.ocr_results:
                st.image(bg_img, width=DISPLAY_WIDTH)
                
                st.info("👇 點擊下方按鈕，AI 將自動偵測每個文字區塊的大小與粗細。")
                
                if st.button("🧠 啟動 AI 智慧排版分析", type="primary", use_container_width=True):
                    with st.spinner("AI 正在分析版面結構與字體..."):
                        engine = get_ocr_engine()
                        img_np = np.array(bg_img)
                        result, elapse = engine(img_np)
                        
                        formatted = []
                        if result:
                            for item in result:
                                coords = item[0]
                                text = item[1]
                                xs = [int(p[0]) for p in coords]
                                ys = [int(p[1]) for p in coords]
                                
                                width = max(xs) - min(xs)
                                height = max(ys) - min(ys)
                                
                                # 智慧推算
                                calc_font_size = max(10, int(height * 0.9))
                                if calc_font_size > 50: calc_stroke = 2 
                                elif calc_font_size > 80: calc_stroke = 3 
                                else: calc_stroke = 0 
                                
                                formatted.append({
                                    'x0': min(xs), 'top': min(ys), 
                                    'x1': max(xs), 'bottom': max(ys),
                                    'orig_x0': min(xs), 'orig_top': min(ys),
                                    'orig_x1': max(xs), 'orig_bottom': max(ys),
                                    'text': text,
                                    'font_size': calc_font_size,
                                    'stroke_width': calc_stroke,
                                    'color': "#000000"
                                })
                        st.session_state.ocr_results[curr] = formatted
                        st.session_state.selected_index = 0 if formatted else None
                        st.session_state.canvas_key += 1 
                    st.rerun()

            # [狀態 B] 已分析
            else:
                initial_drawing = {"version": "4.4.0", "objects": []}
                scale_factor = DISPLAY_WIDTH / bg_img.width
                
                for idx, w in enumerate(st.session_state.ocr_results[curr]):
                    is_selected = (st.session_state.selected_index == idx)
                    stroke_color = "rgba(255, 0, 0, 0.9)" if is_selected else "rgba(0, 113, 227, 0.6)"
                    stroke_width = 3 if is_selected else 1
                    
                    rect_obj = {
                        "type": "rect",
                        "left": w['x0'] * scale_factor,
                        "top": w['top'] * scale_factor,
                        "width": (w['x1'] - w['x0']) * scale_factor,
                        "height": (w['bottom'] - w['top']) * scale_factor,
                        "fill": "rgba(0,0,0,0)",
                        "stroke": stroke_color,
                        "strokeWidth": stroke_width,
                        "angle": 0,
                        "selectable": True,
                        "data": {"index": idx} 
                    }
                    initial_drawing["objects"].append(rect_obj)

                # 這裡使用經過清洗的 bg_img，應該不會再黑屏了
                canvas_result = st_canvas(
                    fill_color="rgba(0, 113, 227, 0.1)",
                    stroke_color="rgba(0, 113, 227, 0.8)",
                    background_image=bg_img, 
                    initial_drawing=initial_drawing,
                    update_streamlit=True,
                    width=DISPLAY_WIDTH,
                    height=int(bg_img.height * scale_factor),
                    drawing_mode="transform", 
                    key=f"canvas_{curr}_{st.session_state.canvas_key}",
                )

                if canvas_result.json_data and "objects" in canvas_result.json_data:
                    objects = canvas_result.json_data["objects"]
                    if len(objects) == len(st.session_state.ocr_results[curr]):
                        needs_rerun = False
                        for i, obj in enumerate(objects):
                            new_x0 = obj["left"] / scale_factor
                            new_top = obj["top"] / scale_factor
                            new_x1 = (obj["left"] + obj["width"]) / scale_factor
                            new_bottom = (obj["top"] + obj["height"]) / scale_factor
                            old_data = st.session_state.ocr_results[curr][i]
                            
                            if (abs(new_x0 - old_data['x0']) > 1 or abs(new_top - old_data['top']) > 1 or
                                abs(new_x1 - old_data['x1']) > 1 or abs(new_bottom - old_data['bottom']) > 1):
                                st.session_state.ocr_results[curr][i]['x0'] = new_x0
                                st.session_state.ocr_results[curr][i]['top'] = new_top
                                st.session_state.ocr_results[curr][i]['x1'] = new_x1
                                st.session_state.ocr_results[curr][i]['bottom'] = new_bottom
                                
                                if st.session_state.selected_index != i:
                                    st.session_state.selected_index = i
                                    st.session_state.editing_text = old_data['text']
                                    needs_rerun = True
                                else:
                                    needs_rerun = True
                        if needs_rerun: st.rerun()

        # === 右側：編輯面板 ===
        with col_edit:
            st.subheader("🛠️ 編輯面板")
            
            c_undo, c_redo = st.columns(2)
            with c_undo:
                has_history = (curr in st.session_state.history and len(st.session_state.history[curr]) > 0)
                if st.button("↩️ 上一步", disabled=not has_history, use_container_width=True):
                    if perform_undo(curr):
                        st.session_state.canvas_key += 1
                        st.rerun()
            with c_redo:
                has_redo = (curr in st.session_state.history_redo and len(st.session_state.history_redo[curr]) > 0)
                if st.button("↪️ 重做", disabled=not has_redo, use_container_width=True):
                    if perform_redo(curr):
                        st.session_state.canvas_key += 1
                        st.rerun()

            current_results = st.session_state.ocr_results.get(curr, [])
            if not current_results:
                st.info("等待分析...")
            else:
                with st.expander("⚡ 智慧重算"):
                    if st.button("🔄 依據框高重新計算所有字體", use_container_width=True):
                        for item in st.session_state.ocr_results[curr]:
                            h = item['bottom'] - item['top']
                            f_size = max(10, int(h * 0.9))
                            item['font_size'] = f_size
                            if f_size > 50: item['stroke_width'] = 2
                            elif f_size > 80: item['stroke_width'] = 3
                            else: item['stroke_width'] = 0
                        st.success("已重算！")
                        st.rerun()

                st.markdown("---")

                options = [f"{i+1}. {w['text'][:15]}..." for i, w in enumerate(current_results)]
                if st.session_state.selected_index is None or st.session_state.selected_index >= len(options):
                    st.session_state.selected_index = 0
                
                selected_opt = st.selectbox("🎯 選擇區塊", options, index=st.session_state.selected_index)
                
                new_index = options.index(selected_opt)
                if new_index != st.session_state.selected_index:
                    st.session_state.selected_index = new_index
                    w = current_results[new_index]
                    st.session_state.editing_text = w['text']
                    st.session_state.canvas_key += 1
                    st.rerun()

                idx = st.session_state.selected_index
                w = current_results[idx]
                
                if not st.session_state.editing_text:
                    st.session_state.editing_text = w['text']

                if 'font_size' not in w: w['font_size'] = 30
                if 'stroke_width' not in w: w['stroke_width'] = 1
                if 'color' not in w: w['color'] = "#000000"

                with st.form("edit_form"):
                    st.caption(f"編輯中：#{idx+1}")
                    new_val = st.text_area("內容", value=st.session_state.editing_text, height=100)
                    
                    c_pos1, c_pos2 = st.columns(2)
                    with c_pos1: adj_x = st.number_input("X", value=int(w['x0']), step=5)
                    with c_pos2: adj_y = st.number_input("Y", value=int(w['top']), step=5)
                        
                    st.markdown("---")
                    c1, c2 = st.columns(2)
                    with c1:
                        f_size = st.number_input("字體大小", 10, 500, w['font_size'])
                    with c2:
                        f_color = st.color_picker("顏色", w['color'])
                    
                    stroke_w = st.slider("筆畫加粗", 0, 5, w['stroke_width'])
                    
                    submitted = st.form_submit_button("✨ 套用修改", use_container_width=True, type="primary")
                
                if submitted:
                    st.session_state.editing_text = new_val
                    
                    # 存 Undo
                    if curr in st.session_state.pages_data:
                        # 已經是 bytes，直接讀取
                        current_img_bytes = st.session_state.pages_data[curr]
                    else:
                        # 第一次存，進行清洗並轉 bytes
                        current_img = page.to_image(resolution=150).original
                        current_img = sanitize_image(current_img)
                        b = io.BytesIO()
                        current_img.save(b, format="PNG")
                        current_img_bytes = b.getvalue()
                    save_history(curr, current_img_bytes)
                    
                    # 繪圖
                    if curr in st.session_state.pages_data:
                        base = Image.open(io.BytesIO(st.session_state.pages_data[curr]))
                        base = sanitize_image(base)
                    else:
                        base = page.to_image(resolution=150).original
                        base = sanitize_image(base)
                    
                    final_draw = ImageDraw.Draw(base)
                    
                    if 'orig_x0' in w:
                        erase_coords = [w['orig_x0'], w['orig_top'], w['orig_x1'], w['orig_bottom']]
                    else:
                        erase_coords = [w['x0'], w['top'], w['x1'], w['bottom']]
                    final_draw.rectangle(erase_coords, fill="white")
                    
                    try:
                        if FONT_PATH_NORMAL and os.path.exists(FONT_PATH_NORMAL):
                             font = ImageFont.truetype(FONT_PATH_NORMAL, f_size)
                        else:
                             font = ImageFont.load_default()
                    except:
                        font = ImageFont.load_default()
                    
                    final_draw.text((adj_x, adj_y), new_val, fill=f_color, font=font, stroke_width=stroke_w)
                    
                    buf = io.BytesIO()
                    base.save(buf, format="PNG")
                    st.session_state.pages_data[curr] = buf.getvalue()
                    
                    st.session_state.ocr_results[curr][idx]['x0'] = adj_x
                    st.session_state.ocr_results[curr][idx]['top'] = adj_y
                    width = w['x1'] - w['x0']
                    height = w['bottom'] - w['top']
                    st.session_state.ocr_results[curr][idx]['x1'] = adj_x + width
                    st.session_state.ocr_results[curr][idx]['bottom'] = adj_y + height
                    
                    st.session_state.ocr_results[curr][idx]['font_size'] = f_size
                    st.session_state.ocr_results[curr][idx]['stroke_width'] = stroke_w
                    st.session_state.ocr_results[curr][idx]['color'] = f_color
                    
                    st.session_state.canvas_key += 1
                    st.success("修改成功！")
                    st.rerun()

            st.divider()
            st.subheader("📦 匯出")
            export_format = st.radio("格式", ["PDF", "PPTX"], horizontal=True)
            
            if st.button("🚀 下載檔案", use_container_width=True):
                if not st.session_state.pages_data:
                    st.warning("請先修改內容")
                else:
                    img_list = []
                    for i in range(total_pages):
                        if i in st.session_state.pages_data:
                            img_list.append(st.session_state.pages_data[i])
                        else:
                            p = pdf.pages[i].to_image(resolution=150).original
                            p = sanitize_image(p) # 確保匯出時也是正常顏色
                            b = io.BytesIO()
                            p.save(b, format="PNG")
                            img_list.append(b.getvalue())

                    if export_format == "PDF":
                        pdf_bytes = img2pdf.convert(img_list)
                        st.download_button("💾 下載 PDF", pdf_bytes, "final_cloud_fixed.pdf")
                    else:
                        prs = Presentation()
                        prs.slide_width = Inches(13.333)
                        prs.slide_height = Inches(7.5)
                        for img_bytes in img_list:
                            slide = prs.slides.add_slide(prs.slide_layouts[6])
                            slide.shapes.add_picture(io.BytesIO(img_bytes), 0, 0, width=Inches(13.333))
                        ppt_out = io.BytesIO()
                        prs.save(ppt_out)
                        st.download_button("💾 下載 PPTX", ppt_out.getvalue(), "final_cloud_fixed.pptx")
else:
    st.info("請上傳 PDF 開始...")
