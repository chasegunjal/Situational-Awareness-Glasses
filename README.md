# Wearable Vision Augmentation System

A Raspberry Pi 5-based wearable vision augmentation prototype designed to provide real-time visual assistance through dual-camera imaging, image enhancement, wireless video streaming, and mobile VR visualization.

## 📌 Project Overview

This project implements a portable vision system using a Raspberry Pi 5 and two camera modules. The system allows the user to switch between a night-vision/no-IR camera and a normal camera with real-time OpenCV-based image enhancement.

The processed video is streamed wirelessly to an Android mobile device using **MJPEG over HTTP**, where it can be viewed normally or in a VR-style split-screen mode.

## 🎯 Objectives

- Capture real-time video using Raspberry Pi camera modules.
- Provide two selectable visual modes.
- Enhance the normal camera feed using OpenCV.
- Stream live video wirelessly to a mobile device.
- Provide a VR-style binocular display.
- Allow image capture directly from the mobile interface.
- Demonstrate a low-cost embedded wearable vision platform.

## 🏗️ System Architecture

```text
          ┌───────────────────┐
          │   Camera 0        │
          │   No-IR / Night   │
          └─────────┬─────────┘
                    │
                    │
          ┌─────────▼─────────┐
          │   Raspberry Pi 5  │
          │                   │
          │    rpicam-vid     │
          │         │         │
          │         ▼         │
          │   Frame Buffer    │
          │         │         │
          │         ▼         │
          │      OpenCV       │
          │  ISO + Denoising  │
          │         │         │
          │         ▼         │
          │   Flask Server    │
          └─────────┬─────────┘
                    │
                 Wi-Fi
                    │
                    ▼
          ┌───────────────────┐
          │   Android Phone   │
          │    Web Browser    │
          └─────────┬─────────┘
                    │
             ┌──────┴──────┐
             │             │
             ▼             ▼
        Normal View     VR View
