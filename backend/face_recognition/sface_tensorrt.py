"""SFace TensorRT features with the existing OpenCV alignment convention."""
from pathlib import Path
from threading import Lock

import numpy as np


class SFaceTensorRTRecognizer:
    def __init__(self, model_path):
        import cv2
        import tensorrt as trt
        import torch

        path = Path(model_path)
        # Keep OpenCV's exact alignCrop implementation; the sibling ONNX is
        # loaded only for alignment, never used for feature inference here.
        self._aligner = cv2.FaceRecognizerSF_create(str(path.with_suffix('.onnx')), '')
        self._cv2, self._torch = cv2, torch
        self._lock = Lock()
        self._logger = trt.Logger(trt.Logger.ERROR)
        self._runtime = trt.Runtime(self._logger)
        self._engine = self._runtime.deserialize_cuda_engine(path.read_bytes())
        if self._engine is None:
            raise RuntimeError('SFace TensorRT engine could not be loaded')
        self._context = self._engine.create_execution_context()
        if self._context is None:
            raise RuntimeError('SFace TensorRT context could not be created')
        names = [self._engine.get_tensor_name(i) for i in range(self._engine.num_io_tensors)]
        inputs = [n for n in names if self._engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT]
        outputs = [n for n in names if self._engine.get_tensor_mode(n) == trt.TensorIOMode.OUTPUT]
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError('SFace requires one input and one output')
        self._input_name, self._output_name = inputs[0], outputs[0]
        buffers = []
        for name, shape in [(inputs[0], (1, 3, 112, 112)), (outputs[0], (1, 128))]:
            if tuple(self._engine.get_tensor_shape(name)) != shape:
                raise ValueError(f'Unexpected SFace tensor shape: {name}')
            dtype = self._engine.get_tensor_dtype(name)
            if dtype not in (trt.float32, trt.float16):
                raise ValueError(f'Unexpected SFace tensor dtype: {dtype}')
            tensor = torch.empty(shape, device='cuda:0', dtype=torch.float32 if dtype == trt.float32 else torch.float16)
            if not self._context.set_tensor_address(name, tensor.data_ptr()):
                raise RuntimeError(f'Cannot bind SFace tensor: {name}')
            buffers.append(tensor)
        self._input, self._output = buffers

    def alignCrop(self, image, face):
        return self._aligner.alignCrop(image, face)

    def feature(self, aligned):
        if aligned.shape != (112, 112, 3) or aligned.dtype != np.uint8:
            raise ValueError('SFace expects an aligned 112x112 uint8 BGR face')
        # SFace ONNX contains normalization; match OpenCV's RGB, scale=1 input.
        blob = self._cv2.dnn.blobFromImage(aligned, 1, (112, 112), (0, 0, 0), True, False)
        with self._lock, self._torch.inference_mode():
            self._input.copy_(self._torch.from_numpy(blob))
            stream = self._torch.cuda.current_stream(device='cuda:0')
            if not self._context.execute_async_v3(stream_handle=stream.cuda_stream):
                raise RuntimeError('SFace TensorRT inference failed')
            result = self._output.float().cpu().numpy().copy()
        if not np.isfinite(result).all() or np.linalg.norm(result) <= 1e-8:
            raise ValueError('SFace TensorRT returned invalid features')
        return result
