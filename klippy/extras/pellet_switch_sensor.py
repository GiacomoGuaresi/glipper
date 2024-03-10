# Ginger Pellet Sensor Module and feeder attivaction
# Developed for the GingerOne Printer auto Feeder extension
#
# Copyright (C) 2024 Giacomo Guaresi <giacomo.guaresi@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import threading
import time
import logging
from datetime import datetime

class RunoutHelper:
    def __init__(self):
        self.sensor_state = False  # Stato iniziale del sensore
        self.last_sensor_state = None  # Stato precedente del sensore
        self.debounce_interval = 1.0  # Intervallo di debounce in secondi
        self.last_state_change_time = time.time()
        self.sensor_action_taken = False
        self.rele_result = True

        #impostazioni della classe
        self.sensor_enabled = True

        # Creazione del thread per il debounce
        self.debounce_thread = threading.Thread(target=self._debounce_thread)
        self.debounce_thread.daemon = True  # Il thread si fermerà quando il programma principale termina
        self.debounce_thread.start()

        # Register commands and event handlers
        self.gcode.register_mux_command(
            "QUERY_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_QUERY_FILAMENT_SENSOR,
            desc=self.cmd_QUERY_FILAMENT_SENSOR_help)
        self.gcode.register_mux_command(
            "SET_FILAMENT_SENSOR", "SENSOR", self.name,
            self.cmd_SET_FILAMENT_SENSOR,
            desc=self.cmd_SET_FILAMENT_SENSOR_help)
    
    def _runout_event_handler(self, eventtime):
        # Pausing from inside an event requires that the pause portion
        # of pause_resume execute immediately.
        pause_prefix = ""
        if self.runout_pause:
            pause_resume = self.printer.lookup_object('pause_resume')
            pause_resume.send_pause_command()
            pause_prefix = "PAUSE\n"
            self.printer.get_reactor().pause(eventtime + 0.5)
        self._exec_gcode(pause_prefix, self.runout_gcode)
        
    def _filledup_event_handler(self, eventtime):
        self._exec_gcode("", self.filledup_gcode)

    def _emergency_event_handler(self, eventtime):
        self._exec_gcode("", self.emergency_gcode)

    def _exec_gcode(self, prefix, template):
        try:
            self.gcode.run_script(prefix + template.render() + "\nM400")
        except Exception:
            logging.exception("Script running error")

    def _debounce_thread(self):
        while True:
            current_time = time.time()

            # Se lo stato è cambiato, resetta il timer di debounce
            if self.sensor_state != self.last_sensor_state:
                self.last_state_change_time = current_time
                self.sensor_action_taken = False
            
            elapsed_time = current_time - self.last_state_change_time

            # Se è trascorso il tempo di debounce, chiamiamo le funzioni in base allo stato del sensore
            if not self.sensor_action_taken and elapsed_time >= self.debounce_interval:
                self.debugPrintOnMonitor("Debounce interval elapsed " + str(elapsed_time) + "s")
                self.debugPrintOnMonitor(" From " + self.format_timestamp(self.last_state_change_time))
                self.debugPrintOnMonitor(" to " + self.format_timestamp(current_time))
                if self.sensor_state:
                    self.on_sensor_true()
                else:
                    self.on_sensor_false()
                self.sensor_action_taken = True

            # Memorizza lo stato corrente del sensore per il prossimo ciclo
            self.last_sensor_state = self.sensor_state

            time.sleep(0.1)  # Sleep per evitare utilizzo eccessivo della CPU

    def note_filament_present(self, is_pellet_present):
        self.debugPrintOnMonitor("Filament Detected" if is_pellet_present else "Filament Not Detected")
        # Verifica se il sensore è abilitato, se non lo è non fa nulla
        if not self.sensor_enabled:
            return

        # Verifica se la stampante è in stampa, nel caso non lo sia non fa nulla
        eventtime = self.reactor.monotonic()
        idle_timeout = self.printer.lookup_object("idle_timeout")
        is_printing = idle_timeout.get_status(eventtime)["state"] == "Printing"
        if not is_printing:
            # Se non è in stampa ma il feeder potrebbe essere acceso spegne e ritorna 
            if self.sensor_state == False:
                self.on_sensor_true()
            return
        
        # Aggiorniamo lo stato del sensore
        self.sensor_state = is_pellet_present

    def on_sensor_true(self):
        # Funzione da eseguire quando lo stato del sensore è True = TRAMOGGIA PIENA
        self.debugPrintOnMonitor("Triggered Filledup Event")
        self.reactor.register_callback(self._filledup_event_handler)
        self.rele_result = False
                    
    def on_sensor_false(self):
        # Funzione da eseguire quando lo stato del sensore è False = TRAMOGGIA VUOTA
        self.debugPrintOnMonitor("Triggered Runout Event")
        self.reactor.register_callback(self._runout_event_handler)
        self.rele_result = True

    def debugPrintOnMonitor(self, msg):
        self.gcode.run_script("M118 " + msg)
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {msg}")

    def format_timestamp(self, timestamp):
        return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]

    def get_status(self, eventtime):
        return {
            "filament_detected": bool(self.pellet_present),
            "enabled": bool(self.sensor_enabled)}
                    
    cmd_QUERY_FILAMENT_SENSOR_help = "Query the status of the pellet Sensor"
    def cmd_QUERY_FILAMENT_SENSOR(self, gcmd):
        if self.pellet_present:
            msg = "Pellet Sensor %s: pellet detected" % (self.name)
        else:
            msg = "Pellet Sensor %s: pellet not detected" % (self.name)
        gcmd.respond_info(msg)
    
    cmd_SET_FILAMENT_SENSOR_help = "Sets the pellet sensor on/off"
    def cmd_SET_FILAMENT_SENSOR(self, gcmd):
        self.sensor_enabled = gcmd.get_int("ENABLE", 1)


class SwitchSensor:
    def __init__(self, config):
        printer = config.get_printer()
        buttons = printer.load_object(config, 'buttons')
        sensor_pin = config.get('sensor_pin')
        buttons.register_buttons([sensor_pin], self._button_handler)
        self.runout_helper = RunoutHelper(config)
        self.get_status = self.runout_helper.get_status
    
    def _button_handler(self, eventtime, state):
        self.runout_helper.note_filament_present(state)


def load_config_prefix(config):
    return SwitchSensor(config)