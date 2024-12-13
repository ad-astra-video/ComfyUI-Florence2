import torch
import torchvision.transforms as T
import torchvision.transforms.functional as F
from torchvision.utils import draw_bounding_boxes
import io
import os
import matplotlib
matplotlib.use('Agg')   
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image, ImageDraw, ImageColor, ImageFont
import random
import numpy as np
import re
from pathlib import Path
import time
import json
import hashlib


#workaround for unnecessary flash_attn requirement
from unittest.mock import patch
from transformers.dynamic_module_utils import get_imports



def fixed_get_imports(filename: str | os.PathLike) -> list[str]:
    try:
        if not str(filename).endswith("modeling_florence2.py"):
            return get_imports(filename)
        imports = get_imports(filename)
        imports.remove("flash_attn")
    except:
        print(f"No flash_attn import to remove")
        pass
    return imports


import comfy.model_management as mm
from comfy.utils import ProgressBar
import folder_paths

script_directory = os.path.dirname(os.path.abspath(__file__))

from transformers import AutoModelForCausalLM, AutoProcessor, AutoImageProcessor

class DownloadAndLoadFlorence2Model:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": (
                    [ 
                    'microsoft/Florence-2-base',
                    'microsoft/Florence-2-base-ft',
                    'microsoft/Florence-2-large',
                    'microsoft/Florence-2-large-ft',
                    ],
                    {
                    "default": 'microsoft/Florence-2-base-ft'
                    }),
            "precision": ([ 'fp16','bf16','fp32'],
                    {
                    "default": 'fp16'
                    }),
            "attention": (
                    [ 'flash_attention_2', 'sdpa', 'eager'],
                    {
                    "default": 'sdpa'
                    }),
            },
            "optional": {
                "lora": ("PEFTLORA",),
            }
        }

    RETURN_TYPES = ("FL2MODEL",)
    RETURN_NAMES = ("florence2_model",)
    FUNCTION = "loadmodel"
    CATEGORY = "Florence2"

    def loadmodel(self, model, precision, attention, lora=None):
        device = mm.get_torch_device()
        offload_device = mm.unet_offload_device()
        dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[precision]

        model_name = model.rsplit('/', 1)[-1]
        model_path = os.path.join(folder_paths.models_dir, "LLM", model_name)
        
        if not os.path.exists(model_path):
            print(f"Downloading Florence2 model to: {model_path}")
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=model,
                            local_dir=model_path,
                            local_dir_use_symlinks=False)
            
        print(f"using {attention} for attention")
        with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports): #workaround for unnecessary flash_attn requirement
            model = AutoModelForCausalLM.from_pretrained(model_path, attn_implementation=attention, device_map=device, torch_dtype=dtype,trust_remote_code=True)
        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        fast_img_proc = AutoImageProcessor.from_pretrained("facebook/detr-resnet-50", size=(768,768), crop_size=(768,768), use_fast=True)
        processor.image_processor = fast_img_proc
        
        if lora is not None:
            from peft import PeftModel
            adapter_name = lora
            model = PeftModel.from_pretrained(model, adapter_name, trust_remote_code=True)
        
        florence2_model = {
            'model': model, 
            'processor': processor,
            'dtype': dtype
            }

        return (florence2_model,)
    
class DownloadAndLoadFlorence2Lora:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": (
                    [ 
                    'NikshepShetty/Florence-2-pixelprose',
                    ],
                  ),            
            },
          
        }

    RETURN_TYPES = ("PEFTLORA",)
    RETURN_NAMES = ("lora",)
    FUNCTION = "loadmodel"
    CATEGORY = "Florence2"

    def loadmodel(self, model):
        model_name = model.rsplit('/', 1)[-1]
        model_path = os.path.join(folder_paths.models_dir, "LLM", model_name)
        
        if not os.path.exists(model_path):
            print(f"Downloading Florence2 lora model to: {model_path}")
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=model,
                            local_dir=model_path,
                            local_dir_use_symlinks=False)
        return (model_path,)
    
class Florence2ModelLoader:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ([item.name for item in Path(folder_paths.models_dir, "LLM").iterdir() if item.is_dir()], {"tooltip": "models are expected to be in Comfyui/models/LLM folder"}),
            "precision": (['fp16','bf16','fp32'],),
            "attention": (
                    [ 'flash_attention_2', 'sdpa', 'eager'],
                    {
                    "default": 'sdpa'
                    }),
            },
            "optional": {
                "lora": ("PEFTLORA",),
            }
        }

    RETURN_TYPES = ("FL2MODEL",)
    RETURN_NAMES = ("florence2_model",)
    FUNCTION = "loadmodel"
    CATEGORY = "Florence2"

    def loadmodel(self, model, precision, attention, lora=None):
        device = mm.get_torch_device()
        dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[precision]
        model_path = Path(folder_paths.models_dir, "LLM", model)
        print(f"Loading model from {model_path}")
        print(f"using {attention} for attention")
        with patch("transformers.dynamic_module_utils.get_imports", fixed_get_imports): #workaround for unnecessary flash_attn requirement
            model = AutoModelForCausalLM.from_pretrained(model_path, attn_implementation=attention, device_map=device, torch_dtype=dtype, trust_remote_code=True)
        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        fast_img_proc = RTDetrImageProcessorFast.from_pretrained("PekingU/rtdetr_r50vd", size=model_img_size, crop_size=model_crop_size)
        processor.image_processor = fast_img_proc
        
        if lora is not None:
            from peft import PeftModel
            adapter_name = lora
            model = PeftModel.from_pretrained(model, adapter_name, trust_remote_code=True)
        
        florence2_model = {
            'model': model, 
            'processor': processor,
            'dtype': dtype
            }
   
        return (florence2_model,)
    
class Florence2Run:
    def __init__(self):
        self.last_hash = ""
        self.last_caption = ""
        self.last_data = ""
        self.device = mm.get_torch_device()
        self.offload_device = mm.unet_offload_device()
        self.prompts = {
            'region_caption': '<OD>',
            'dense_region_caption': '<DENSE_REGION_CAPTION>',
            'region_proposal': '<REGION_PROPOSAL>',
            'caption': '<CAPTION>',
            'detailed_caption': '<DETAILED_CAPTION>',
            'more_detailed_caption': '<MORE_DETAILED_CAPTION>',
            'caption_to_phrase_grounding': '<CAPTION_TO_PHRASE_GROUNDING>',
            'open_vocabulary_detection': '<OPEN_VOCABULARY_DETECTION>',
            'region_to_category': '<REGION_TO_CATEGORY>',
            'region_to_description': '<REGION_TO_DESCRIPTION>',
            'region_to_ocr': '<REGION_TO_OCR>',
            'referring_expression_segmentation': '<REFERRING_EXPRESSION_SEGMENTATION>',
            'region_to_segmentation': '<REGION_TO_SEGMENTATION>',
            'ocr': '<OCR>',
            'ocr_with_region': '<OCR_WITH_REGION>',
        }
        self.uses_text_input = ["referring_expression_segmentation", "caption_to_phrase_grounding", "docvqa", "open_vocabulary_detection"]
        self.text_responses = ["caption", "ocr", "detail_caption", "more_detailed_caption", "region_to_category", "region_to_description", "region_to_ocr"]
        self.includes_bbox = ["region_caption", "dense_region_caption", "caption_to_phrase_grounding", "open_vocabulary_detection", "ocr_with_region"]
        self.includes_polygons = ["referring_expression_segmentation", "region_to_segmentation"]
        self.colors_rgb = {
            "red": (255, 0, 0),
            "orange": (255, 165, 0),
            "green": (0, 255, 0),
            "purple": (128, 0, 128),
            "brown": (165, 42, 42),
            "pink": (255, 192, 203),
            "olive": (128, 128, 0),
            "cyan": (0, 255, 255),
            "blue": (0, 0, 255),
            "lime": (50, 205, 50),
            "indigo": (75, 0, 130),
            "violet": (238, 130, 238),
            "aqua": (0, 255, 255),
            "magenta": (255, 0, 255),
            "gold": (255, 215, 0),
            "tan": (210, 180, 140),
            "skyblue": (135, 206, 235),
        }
        #load font to use
        try:
            self.font = ImageFont.load_default().font_variant(size=24)
        except:
            self.font = ImageFont.load_default()
        
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE", ),
                "florence2_model": ("FL2MODEL", ),
                "text_input": ("STRING", {"default": "", "multiline": True}),
                "mode": (
                    [
                    "on task change",
                    "every frame"
                    ], {"default": "on task change"}
                ),
                "task": (
                    [ 
                    'region_caption',
                    'dense_region_caption',
                    'region_proposal',
                    'caption',
                    'detailed_caption',
                    'more_detailed_caption',
                    'caption_to_phrase_grounding',
                    'open_vocabulary_detection',
                    'region_to_category',
                    'region_to_description',
                    'referring_expression_segmentation',
                    'ocr',
                    'ocr_with_region',
                    ],
                   ),
                "annotation_color": (
                    ['red','orange','green','purple','brown','pink','olive','cyan','blue',
                    'lime','indigo','violet','aqua','magenta','gold','tan','skyblue'], {"default": "red"} #note, add to self.colors_rgb in __init__ if changed
                   ),
                "keep_model_loaded": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "output_mask_select": ("STRING", {"default": ""}),
                "fill_mask": ("BOOLEAN", {"default": False}),
                "max_new_tokens": ("INT", {"default": 1024, "min": 1, "max": 4096}),
                "num_beams": ("INT", {"default": 1, "min": 1, "max": 64}),
                "do_sample": ("BOOLEAN", {"default": False}),
            }
        }
    
    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "JSON", "STRING")
    RETURN_NAMES =("image", "mask", "caption", "data", "processing_stats") 
    FUNCTION = "encode"
    CATEGORY = "Florence2"

    def process(self, model, input_ids, pixel_values, max_new_tokens, do_sample, num_beams):
        kwargs = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "num_beams": num_beams,
        }
        
        return model.generate(
                input_ids=input_ids,
                pixel_values=pixel_values,
                **kwargs,
            )

    def process_polygons_and_labels(self, image_pil, polygons, labels, fill_mask=False, annotation_color=(255, 0, 0)):
        # Create a new black image
        mask_image = Image.new('RGB', (W, H), 'black')
        mask_draw = ImageDraw.Draw(mask_image)
        
        # Iterate over polygons and labels  
        for polygons, label in zip(predictions['polygons'], predictions['labels']):
            for _polygon in polygons:  
                _polygon = np.array(_polygon).reshape(-1, 2)
                # Clamp polygon points to image boundaries
                _polygon = np.clip(_polygon, [0, 0], [W - 1, H - 1])
                if len(_polygon) < 3:  
                    print('Invalid polygon:', _polygon)
                    continue  
                
                _polygon = _polygon.reshape(-1).tolist()
                
                # Draw the polygon
                if fill_mask:
                    overlay = Image.new('RGBA', image_pil.size, (255, 255, 255, 0))
                    image_pil = image_pil.convert('RGBA')
                    draw = ImageDraw.Draw(overlay)
                    color_with_opacity = ImageColor.getrgb(annotation_color) + (180,)
                    draw.polygon(_polygon, outline=annotation_color, fill=color_with_opacity, width=3)
                    image_pil = Image.alpha_composite(image_pil, overlay)
                else:
                    draw = ImageDraw.Draw(image_pil)
                    draw.polygon(_polygon, outline=annotation_color, width=3)

                #draw mask
                mask_draw.polygon(_polygon, outline="white", fill="white")
                
        annotated_image_tensor = F.to_tensor(image_pil)
        annotated_image_tensor = annotated_image_tensor[:3, :, :].unsqueeze(0).permute(0, 2, 3, 1).cpu().float() 

        mask_tensor = F.to_tensor(mask_image)
        mask_tensor = mask_tensor.unsqueeze(0).permute(0, 2, 3, 1).cpu().float()
        mask_tensor = mask_tensor.mean(dim=0, keepdim=True)
        mask_tensor = mask_tensor.repeat(1, 1, 1, 3)
        mask_tensor = mask_tensor[:, :, :, 0]
        
        return annotated_image_tensor, mask_tensor
                
    def process_bboxes_and_labels(self, image_pil, boxes, labels, mask_indexes, fill_mask=False, annotation_color=(255, 0, 0), exclude_labels=False):
        W, H = image_pil.size  # Image dimensions
        
        # Initialize mask_layer only if needed
        if fill_mask:
            mask_layer = Image.new('RGB', image_pil.size, (0, 0, 0))  # Blank mask image
            mask_draw = ImageDraw.Draw(mask_layer)
        
        # Convert image to RGB format if needed
        draw = ImageDraw.Draw(image_pil)
        
        # Draw bounding boxes and labels
        for index, (box, label) in enumerate(zip(boxes, labels)):
            # Modify the label to include the index
            indexed_label = f"{index}.{label}" if not exclude_labels else f"{index}"
            
            # Draw bounding box
            # most tasks return bboxes [x0,y0,x1,y1]
            # ocr_with_region returns quad_boxes [x0,y0 ... x3,y3]
            x0 = box[0]
            y0 = box[1] if len(box) == 4 else box[1]
            x1 = box[2] if len(box) == 4 else max(box[0], box[2]+5) #small buffer to make sure is larger
            y1 = box[3] if len(box) == 4 else max(box[1], box[7]+5) #small buffer to make sure is larger
            
            draw.rectangle([x0, y0, x1, y1], outline=annotation_color, width=2)
            
            # Optionally add label
            text_width = len(label) * 6  # Adjust multiplier based on your font size
            text_height = 12  # Adjust based on your font size
            
            # Initial text position
            text_x = x0
            text_y = y0 - text_height  # Position text above the top-left of the bbox
            
            # Adjust text_x if text is going off the left or right edge
            if text_x < 0:
                text_x = 0
            elif text_x + text_width > W:
                text_x = W - text_width
            
            # Adjust text_y if text is going off the top edge
            if text_y < 0:
                text_y = y1  # Move text below the bottom-left of the bbox if it doesn't overlap with bbox
            
            # Add the label text
            draw.text((text_x, text_y), indexed_label, fill=annotation_color)
            
            # Optionally add the mask
            if fill_mask:
                if str(index) in mask_indexes or labels[index] in mask_indexes:
                    mask_draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))
        
        if fill_mask:
            # Convert mask layer to tensor and process
            mask_tensor = F.to_tensor(mask_layer)
            mask_tensor = mask_tensor.unsqueeze(0).permute(0, 2, 3, 1).cpu().float()
            mask_tensor = mask_tensor.mean(dim=0, keepdim=True)
            mask_tensor = mask_tensor.repeat(1, 1, 1, 3)
            mask_tensor = mask_tensor[:, :, :, 0]
        else:
            mask_tensor = None
            
        # Convert the annotated image back to tensor
        annotated_image_tensor = F.to_tensor(image_pil)
        annotated_image_tensor = annotated_image_tensor[:3, :, :].unsqueeze(0).permute(0, 2, 3, 1).cpu().float() 
        
        return annotated_image_tensor, mask_tensor
    
    def skip_encode(self, text_input, task, annotation_color, output_mask_select):
        check = "".join([text_input, task, annotation_color, output_mask_select])
        
        hash = hashlib.sha256(check.encode('utf-8')).hexdigest()
        if hash != self.last_hash:
            self.last_hash = hash
            print("hashed monitored inputs: ", hash)
            return False
        else:
            return True
    
    def track_processing_stats(self, processing_stats, task, time):
        if task == "preprocess":
            processing_stats["preprocess_ms"] = time
        elif task == "generate":
            processing_stats["generate_ms"] = time - processing_stats["total_ms"]
        elif task == "postprocess":
            processing_stats["postprocess_ms"] = time - processing_stats["total_ms"]
        elif task == "annotate":
            processing_stats["annotate_ms"] = time - processing_stats["total_ms"]
            processing_stats.pop("total_ms")
        
        #track total to get time by step and add at end for final total
        processing_stats["total_ms"] = time
        
        return processing_stats
        
    def encode(self, image, text_input, florence2_model, mode, task, annotation_color, fill_mask, keep_model_loaded=True, 
            num_beams=1, max_new_tokens=1024, do_sample=True, output_mask_select=""):
        
        if mode == "on task change" and self.skip_encode(text_input, task, annotation_color, output_mask_select):
            return (image, torch.zeros((1,64,64), dtype=torch.float32, device="cpu"), self.last_caption, self.last_data)
        
        _, height, width, _ = image.shape
        annotated_image_tensor = None
        mask_tensor = None
        processor = florence2_model['processor']
        model = florence2_model['model']
        dtype = florence2_model['dtype']
        model.to(self.device)
        
        task_prompt = self.prompts.get(task, '<OD>')

        if task in self.uses_text_input:
            prompt = task_prompt + " " + text_input
        else:
            prompt = task_prompt

        image = image.permute(0, 3, 1, 2)
        
        out = []
        out_masks = []
        out_results = []
        out_data = []
        pbar = ProgressBar(len(image))
        processing_stats = {}
        for img in image:
            start = time.time()
            
            image_pil = F.to_pil_image(img)
            inputs = processor(text=prompt, images=image_pil, return_tensors="pt").to(dtype).to(self.device)
            self.track_processing_stats(processing_stats, "preprocess", int((time.time()-start)*1000))
            
            generated_ids = self.process(
                model,
                inputs["input_ids"],
                inputs["pixel_values"],
                max_new_tokens,
                do_sample,
                num_beams,
            )
            
            self.track_processing_stats(processing_stats, "generate", int((time.time()-start)*1000))
            
            results = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
            
            # cleanup the special tokens from the final list
            if task == 'ocr_with_region':
                clean_results = str(results)
                cleaned_string = re.sub(r'</?s>|<[^>]*>', '\n',  clean_results)
                clean_results = re.sub(r'\n+', '\n', cleaned_string)
            else:
                clean_results = str(results)
                clean_results = clean_results.replace('</s>', '')
                clean_results = clean_results.replace('<s>', '')

             #return single string if only one image for compatibility with nodes that can't handle string lists
            if len(image) == 1:
                out_results = clean_results
            else:
                out_results.append(clean_results)

            W, H = image_pil.size
            parsed_answer = processor.post_process_generation(results, task=task_prompt, image_size=(W, H))
            self.track_processing_stats(processing_stats, "postprocess", int((time.time()-start)*1000))
            
            if task in self.includes_polygons:
                predictions = parsed_answer[task_prompt]
                
                out_tensor, out_mask = self.process_polygons_and_labels(image_pil, predications['polygons'], predictions['labels'], fill_mask, self.colors_rgb[annotation_color])
                
                out.append(out_tensor)
                if fill_mask:
                    out_masks.append(out_mask)
                    
                pbar.update(1)
            elif task in self.includes_bbox:
                bboxes = parsed_answer[task_prompt]['bboxes'] if not task == "ocr_with_region" else parsed_answer[task_prompt]['quad_boxes']
                labels_key = "labels" if not task == "open_vocabulary_detection" else "bboxes_labels"
                labels = parsed_answer[task_prompt][labels_key]
                exclude_labels_annotation = True if task == "ocr_with_region" else False
                
                mask_indexes = []
                if output_mask_select != "":
                    mask_indexes = [n for n in output_mask_select.split(",")]
                    #print(mask_indexes)
                else:
                    mask_indexes = [str(i) for i in range(len(bboxes))]
                
                out_tensor, out_mask = self.process_bboxes_and_labels(image_pil, bboxes, labels, mask_indexes, fill_mask, self.colors_rgb[annotation_color], exclude_labels_annotation)
                
                out.append(out_tensor)
                out_data.append(bboxes)
                if fill_mask:
                    out_masks.append(out_mask)
                
                pbar.update(1)
            
            self.track_processing_stats(processing_stats, "annotate", int((time.time()-start)*1000))
            self.track_processing_stats(processing_stats, "total", int((time.time()-start)*1000))
            
        #final processing for outputs
        if len(out) > 0:
            out_tensor = torch.cat(out, dim=0)
        else:
            out_tensor = torch.zeros((1, 64,64, 3), dtype=torch.float32, device="cpu")
        if len(out_masks) > 0:
            out_mask_tensor = torch.cat(out_masks, dim=0)
        else:
            out_mask_tensor = torch.zeros((1,64,64), dtype=torch.float32, device="cpu")

        if not keep_model_loaded:
            print("Offloading model...")
            model.to(self.offload_device)
            mm.soft_empty_cache()
        
        self.last_caption = out_results
        self.last_data = out_data
        
        return (out_tensor, out_mask_tensor, out_results, out_data, json.dumps(processing_stats))

class BoundingBoxToCenter:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "bbox_data": ("JSON",),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("center_coordinates",)
    FUNCTION = "convert_bbox_to_center"
    CATEGORY = "Florence2"

    def convert_bbox_to_center(self, bbox_data):
        try:
            center_coords = []
            
            for bbox in bbox_data[0]:
                bl_x, bl_y, tr_x, tr_y = bbox

                center_x = int((bl_x + tr_x) / 2)
                center_y = int((bl_y + tr_y) / 2)

                center_coords.append((center_x, center_y))
                
            coords_str = json.dumps(center_coords, separators=(',', ':'))
            return (coords_str,)

        except (ValueError, SyntaxError, IndexError) as e:
            print(f"Error processing bounding box data: {e}")
            return ("[[0, 0]]",)

NODE_CLASS_MAPPINGS = {
    "DownloadAndLoadFlorence2Model": DownloadAndLoadFlorence2Model,
    "DownloadAndLoadFlorence2Lora": DownloadAndLoadFlorence2Lora,
    "Florence2ModelLoader": Florence2ModelLoader,
    "Florence2Run": Florence2Run,
    "BoundingBoxToCenter": BoundingBoxToCenter
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DownloadAndLoadFlorence2Model": "DownloadAndLoadFlorence2Model",
    "DownloadAndLoadFlorence2Lora": "DownloadAndLoadFlorence2Lora",
    "Florence2ModelLoader": "Florence2ModelLoader",
    "Florence2Run": "Florence2Run",
    "BoundingBoxToCenter": "BBOX to Center Point"
}