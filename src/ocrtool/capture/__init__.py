"""屏幕捕获子包（spec: screen-capture）。

screen_capture 负责像素捕获与逐屏坐标换算，region_overlay 负责冻结帧
选区界面与整个截图流程的生命周期。识别复用既有管线，此处不接触引擎。
"""
