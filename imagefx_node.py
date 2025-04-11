import os
import requests
import base64
import json
import time
import folder_paths
from PIL import Image
import io
import numpy as np
import uuid
import torch
from io import BytesIO

class ImageFXAPINode:
    """
    调用ImageFX API生成图片的ComfyUI节点
    基于官方API实现，完全匹配原始请求格式
    """
    
    def __init__(self):
        # 从环境变量或配置文件获取认证令牌
        self.auth_token = self._get_auth_token()
        # 实际API端点
        self.api_url = "https://aisandbox-pa.googleapis.com/v1:runImageFx"
        # 确保有一个文件夹来保存生成的图片
        self.output_dir = os.path.join(folder_paths.get_output_directory(), "imagefx_outputs")
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        # 调试模式
        self.debug = True
    
    def log(self, message):
        """记录日志信息（如果调试模式开启）"""
        if self.debug:
            print(f"[ImageFX] {message}")
    
    def _get_auth_token(self):
        """获取认证令牌，优先从环境变量读取，然后尝试从.auth文件读取"""
        # 从环境变量读取
        auth_token = os.environ.get("IMAGEFX_AUTH_TOKEN", "")
        
        # 如果环境变量中没有，尝试从.auth文件读取
        if not auth_token:
            auth_file_path = os.path.join(os.path.dirname(__file__), "ifx_config.auth")
            if os.path.exists(auth_file_path):
                try:
                    with open(auth_file_path, "r") as f:
                        auth_token = f.read().strip()
                except Exception as e:
                    self.log(f"读取.auth文件失败: {str(e)}")
        
        return auth_token
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True}),
            },
            "optional": {
                "image_count": ("INT", {"default": 4, "min": 1, "max": 10}),
                "seed": ("INT", {"default": -1}),  # -1表示随机种子
                "aspect_ratio": (["LANDSCAPE", "PORTRAIT", "SQUARE"], {"default": "LANDSCAPE"}),
                "model_type": (["IMAGEN_3_1"], {"default": "IMAGEN_3_1"}),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "IMAGE",)
    RETURN_NAMES = ("image1", "image2", "image3", "image4",)
    FUNCTION = "generate_images"
    CATEGORY = "image/external"
    
    def generate_empty_image(self, width=512, height=512):
        """生成标准格式的空白RGB图像张量"""
        empty_image = np.ones((height, width, 3), dtype=np.float32) * 0.2
        tensor = torch.from_numpy(empty_image).unsqueeze(0)  # [1, H, W, 3]
        
        self.log(f"创建ComfyUI兼容的空白图像: 形状={tensor.shape}, 类型={tensor.dtype}")
        return tensor
    
    def convert_pil_to_tensor(self, pil_image):
        """将单个PIL图像转换为ComfyUI兼容的张量格式"""
        try:
            # 确保是RGB模式
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
                self.log(f"已将图像转换为RGB模式")
            
            # 转换为ComfyUI格式
            img_array = np.array(pil_image).astype(np.float32) / 255.0
            img_tensor = torch.from_numpy(img_array).unsqueeze(0)  # [1, H, W, 3]
            
            self.log(f"PIL图像成功转换为张量: 形状={img_tensor.shape}, 类型={img_tensor.dtype}")
            return img_tensor
        
        except Exception as e:
            self.log(f"PIL转张量失败: {str(e)}")
            # 返回空白图像作为后备
            return self.generate_empty_image()
    
    def generate_images(self, prompt, image_count=4, seed=-1,
                       aspect_ratio="LANDSCAPE", model_type="IMAGEN_3_1"):
        """
        调用ImageFX API生成图片
        """
        if not self.auth_token:
            raise ValueError("未设置ImageFX认证令牌，请设置环境变量IMAGEFX_AUTH_TOKEN或创建.auth文件")
        
        # 创建会话ID（使用时间戳，类似于示例代码）
        session_id = f";{int(time.time() * 1000)}"
        
        # 确保认证令牌格式正确（添加Bearer前缀）
        auth_header = self.auth_token
        if not auth_header.startswith("Bearer "):
            auth_header = "Bearer " + auth_header
        
        # 构建API请求头（完全匹配原始请求）
        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "text/plain;charset=UTF-8",
            "dnt": "1",
            "origin": "https://labs.google",
            "priority": "u=1, i",
            "referer": "https://labs.google/",
            "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "cross-site",
            "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "authorization": auth_header
        }
        
        # 将aspect_ratio转换为API需要的格式
        aspect_ratio_value = f"IMAGE_ASPECT_RATIO_{aspect_ratio}"
        
        # 处理种子值
        seed_value = seed if seed > 0 else None
        
        # 构建请求体
        payload = {
            "userInput": {
                "candidatesCount": image_count,
                "prompts": [prompt],
                "seed": seed_value,
            },
            "clientContext": {
                "sessionId": session_id,
                "tool": "IMAGE_FX",
            },
            "modelInput": {
                "modelNameType": model_type,
            },
            "aspectRatio": aspect_ratio_value,
        }
        
        try:
            self.log(f"正在发送请求到ImageFX API...")
            self.log(f"提示词: {prompt}")
            self.log(f"图片数量: {image_count}")
            self.log(f"宽高比: {aspect_ratio}")
            
            # 发送API请求
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload
            )
            
            if response.status_code != 200:
                self.log(f"API响应状态码: {response.status_code}")
                self.log(f"API响应内容: {response.text}")
                raise Exception(f"API请求失败: {response.status_code} {response.text}")
            
            response_data = response.json()
            
            # 检查响应中是否有错误
            if "error" in response_data:
                error_info = response_data["error"]
                error_message = f"API错误: 代码 {error_info.get('code')}, 消息: {error_info.get('message')}, 状态: {error_info.get('status')}"
                self.log(error_message)
                raise Exception(error_message)
            
            # 处理返回的图片
            image_tensors = []
            
            # 遍历所有图像面板
            for panel in response_data.get("imagePanels", []):
                # 遍历每个面板中的所有生成图像
                for image_data in panel.get("generatedImages", []):
                    # 获取Base64编码的图片数据
                    encoded_image = image_data.get("encodedImage", "")
                    image_seed = image_data.get("seed", "unknown")
                    
                    if encoded_image:
                        # 解码Base64图片数据
                        image_bytes = base64.b64decode(encoded_image)
                        
                        # 将字节数据转换为PIL图像
                        pil_image = Image.open(io.BytesIO(image_bytes))
                        
                        # 保存图片到文件
                        filename = f"imagefx_seed{image_seed}_{uuid.uuid4().hex[:8]}.png"
                        save_path = os.path.join(self.output_dir, filename)
                        
                        # 确保是RGB模式后保存
                        if pil_image.mode != 'RGB':
                            pil_image = pil_image.convert('RGB')
                        pil_image.save(save_path)
                        
                        # 转换为ComfyUI张量格式
                        img_tensor = self.convert_pil_to_tensor(pil_image)
                        image_tensors.append(img_tensor)
                        
                        self.log(f"成功生成并保存图片: {filename} (种子: {image_seed})")
            
            self.log(f"总共生成了 {len(image_tensors)} 张图片")
            
            # 检查是否有图片生成
            if len(image_tensors) == 0:
                raise Exception("API没有返回任何图片")
                
            # 如果需要补充到4张图片
            while len(image_tensors) < 4:
                # 获取第一张图片的尺寸
                if image_tensors:
                    first_tensor = image_tensors[0]
                    _, height, width, _ = first_tensor.shape
                    empty_tensor = self.generate_empty_image(width, height)
                else:
                    # 默认尺寸
                    empty_tensor = self.generate_empty_image(512, 512)
                
                image_tensors.append(empty_tensor)
            
            # 只使用前4张图片作为返回值
            return tuple(image_tensors[:4])
            
        except Exception as e:
            self.log(f"发生错误: {str(e)}")
            # 发生错误时返回4张空白图片
            empty_tensors = [self.generate_empty_image() for _ in range(4)]
            return tuple(empty_tensors)

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 确保节点每次运行时都会重新生成图片
        return float("NaN")

# 节点注册函数，需要添加到ComfyUI的custom_nodes文件夹中的某个py文件
NODE_CLASS_MAPPINGS = {
    "ImageFXAPI": ImageFXAPINode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageFXAPI": "ImageFX API Generator"
}

# 安装说明
"""
安装步骤:
1. 将此脚本保存为imagefx_node.py
2. 复制到ComfyUI的custom_nodes文件夹中
3. 创建认证令牌:
   a) 设置环境变量: IMAGEFX_AUTH_TOKEN=你的令牌
   b) 或者创建.auth文件在节点旁边，内容为令牌
4. 重启ComfyUI
5. 在节点浏览器中搜索"ImageFX API Generator"
"""

# 如果直接运行此文件，提供一些基本信息
if __name__ == "__main__":
    print("ImageFX API节点已加载")
    print("请确保设置了IMAGEFX_AUTH_TOKEN环境变量或创建了.auth文件")
    print("将此文件放置在ComfyUI的custom_nodes文件夹中")
