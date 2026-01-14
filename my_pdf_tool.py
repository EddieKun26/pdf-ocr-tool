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
st.set_page_config(page_title="NotebookLM AI 旗艦版 (Palette Fix)", layout="wide")

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

# --- 關鍵修正：針對雲端 P 模式與透明圖層的終極清洗 (暴力白底版) ---
def sanitize_image(pil_image):
    """
    不管圖片原本是什麼格式，一律建立一張「純白」的底圖，
    然後把原圖貼上去。這能確保透明背景一定會變成白色，解決變黑問題。
    """
    # 1. 確保原圖是 RGBA (包含透明度資訊)，這樣貼上時才不會破圖
    pil_image = pil_image.convert('RGBA')
    
    # 2. 建立一張同樣大小的「純白色」底圖
    new_image = Image.new('RGB', pil_image.size, (255, 255, 255))
    
    # 3. 將原圖貼在白底上 (使用 alpha 作為遮罩)
    new_image.paste(pil_image, (0, 0), pil_image)
    
    # 4. 直接回傳這張新的 RGB 圖片
    return new_image

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
        st.session_state.pages_data[page_idx] = st.session_state.
