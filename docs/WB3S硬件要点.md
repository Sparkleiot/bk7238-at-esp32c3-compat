# XH-WB3S (BK7238) 硬件要点 —— 来自《SPARKLEIOT_XH-WB3S模组手册V1.0》

> 本文件是对模组规格书的解读摘要，只保留做 AT 固件时真正需要的信息。

## 1. 核心器件

| 项目 | 参数 | 出处 |
|------|------|------|
| 主控芯片 | **BK7238**（非 ESP 系列） | 一.产品概述 |
| CPU | 32-bit MCU，主频最高 160 MHz（手册「特点」）／表格记 120 MHz | 特点 / 表1.1 |
| 内存 | 288 KB RAM（特点）／表格记 256 KB RAM | 特点 / 表1.1 |
| Flash | 2 MB | 特点 |
| 工作电压 | 3.0 V ~ 3.6 V，典型 3.3 V | 表4.2 |
| 供电能力 | 3.3 V / 350 mA；平均电流 100 mA，**峰值 > 400 mA** | 管脚表 / 表1.1 |
| 工作温度 | -40 ℃ ~ 85 ℃ | 表4.2 |
| 封装 | 16 mm × 24 mm × 3 mm，Pin 间距 2 mm | 表3.1 |
| 天线 | 板载 PCB 天线 | 表1.1 |

**射频**：IEEE 802.11 b/g/n 1×1（信道 1–14，2.4 GHz），BLE 5.2（1M/2M/LR 125k/500k）。
发射功率典型 11b +16 dBm / 11g +15 dBm / 11n +14 dBm。

## 2. 外设资源

`2×UART`、`6×ADC`、`1×SPI`、`6×PWM`、`1×I2C`，另有 SDIO / IrDA / JTAG。

## 3. 引脚定义（22 Pin）

| # | 名称 | 复用功能 |
|---|------|----------|
| 1 | **CEN** | 外部复位，**低电平有效**，模块内部已上拉 |
| 2 | P28 | GPIO / ADC4 |
| 3 | P23 | GPIO |
| 4 | P14 | GPIO / SPI SCK |
| 5 | P26 | GPIO / ADC1 / I2C SDA / PWM5 |
| 6 | P24 | GPIO / ADC2 / 32 kHz 时钟输出 / PWM4 / I2C SCL |
| 7 | P6 | GPIO / 时钟分频输出 / PWM0 / JTAG TCK |
| 8 | **VCC** | 3.3 V / 350 mA |
| 9 | P16 | GPIO / SPI MOSI |
| 10 | P20 | GPIO / ADC3 |
| 11 | P21 | GPIO |
| 12 | P22 | GPIO |
| 13 | P15 | GPIO / SPI CSN / I2C SCL |
| 14 | P17 | GPIO / SPI MISO / I2C SDA |
| 15 | **GND** | 地 |
| 16 | P9 | GPIO / PWM3 / JTAG TDO |
| 17 | P0 | GPIO / **UART2 TXD** |
| 18 | P1 | GPIO / **UART2 RXD** / ADC5 |
| 19 | P8 | GPIO / PWM2 / 26 MHz 时钟输出 |
| 20 | P7 | GPIO / JTAG TMS / PWM1 |
| 21 | **RXD1** | UART_RX1，用户数据接收口，**对应 IC 的 P10**；禁止上拉 |
| 22 | **TXD1** | UART_TX1，用户数据发送口，**对应 IC 的 P11**；禁止上拉 |

> 21/22 脚备注：「MCU 对接串口默认状态需配置成低电平或者高阻态」。

## 4. ★ 关键结论：下载与通信共用同一组串口

手册「表2.1 引脚模式」：

| 模式 | P11 | CEN |
|------|-----|-----|
| **UART 下载模式** | **高** | 高 |
| RF 校准测试 | **低** | 高 |

结合引脚表可知 **P11 即模块第 22 脚 TXD1**，因此：

- 用户数据口就是 UART1：**模块 RXD1(P10) ← 上位机 TX**，**模块 TXD1(P11) → 上位机 RX**；
- 该 UART 同时承担 **固件烧录（芯片内置 bootloader 的 UART 下载协议）** 和 **AT 命令收发**，
  硬件上**不需要**像 ESP32 那样额外拉 GPIO0 / EN 进入下载模式；
- 进入 UART 下载模式的条件是 **CEN = 高（正常运行电平）+ P11 为高**（UART TX 空闲态天然为高，故正常接线即满足）；
- 若要进 RF 校准，才需要把 **Pin11（TXD1）拉低**；
- 复位只需把 **CEN 短接到 GND**（内部上拉，松开即启动）。

这正好对应本项目的硬件接线：CH340 → COM3，`TXD→RXD1(P10)`、`RXD→TXD1(P11)`、`GND↔GND`、`3V3→VCC`。

## 5. 烧录约束（实测 + 手册推导）

- 供电：3.3 V，**峰值 > 400 mA**，务必用独立稳压源或能供 500 mA 以上的 LDO；USB-TTL 的 3.3 V 引脚供电极易失败。
- 模块无自动复位电路时，进入下载需在工具等待握手期间断电重上电（或 CEN 拉低再松开）。
- 实测可用命令（COM3 / CH340 / 2 Mbps）：
  ```
  bk_loader_v4.exe download -p COM3 -b 2000000 -r -i "firmware.bin@0x0-0xFFFFFFF"
  ```
  成功标志：日志出现 `Download complete, all pass`（约 14 s）。

## 6. 与 ESP32-C3 的差异（做 AT 固件时必须抹平的）

| 维度 | ESP32-C3（ESP-AT 原生） | XH-WB3S（BK7238） |
|------|------------------------|-------------------|
| 芯片 | ESP32-C3 (RISC-V) | BK7238 (ARM) |
| Flash | 常见 4 MB | **2 MB**（分区表更紧） |
| RAM | 400 KB | 256~288 KB（AT 功能要裁剪） |
| 下载方式 | GPIO9 拉低 + RST，独立 bootloader 协议 | UART 直连内置 bootloader，同一条串口 |
| 默认 AT 串口 | UART0 (GPIO20/21) 或 UART1 | UART1 = P10/P11（固定） |
| AT 命令集 | ESP-AT 官方 | 需按 ESP-AT 行为逐条对齐 |

> 因此「兼容 ESP32-C3 的 AT 固件」= 在 BK7238 上复刻 **ESP-AT 的命令名 / 参数 / 应答报文格式**，
> 使上位机原有的 ESP-AT 驱动代码**无需修改**即可驱动本模组。
