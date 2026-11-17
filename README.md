# Battery Monitor

Ícone na bandeja do Windows (um por periférico) que mostra a bateria dos seus dispositivos Bluetooth e avisa quando ficar crítica, com som opcional.
Tray app for Windows (one icon per device) that shows the battery of your Bluetooth peripherals and alerts you when it gets critical, with an optional sound.

## Uso / Usage
1. Baixe/Download `BatteryMonitor.exe` e execute / and run it.
2. Arraste os ícones da seta ^ para a barra / Drag the icons from the ^ overflow to the taskbar.
3. Botão direito / Right-click: nível crítico (critical level), som (.wav) e teste de alerta (alert test), idioma (language), iniciar com o Windows (start with Windows).

## Limitações / Limitations
- Só mostra dispositivos que informam bateria ao Windows via Bluetooth. / Only devices that report battery to Windows over Bluetooth. Dongles 2.4GHz não são suportados / are not supported.
- O Windows SmartScreen pode avisar "app desconhecido" (o .exe não é assinado): *Mais informações → Executar assim mesmo*. / SmartScreen may warn about an unknown app (unsigned): *More info → Run anyway*.

## Compilar / Build
```
pip install pystray pillow pyinstaller
pyinstaller --noconsole --onefile --name BatteryMonitor --icon icon.ico battery_monitor.py
```
