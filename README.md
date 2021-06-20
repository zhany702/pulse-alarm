# pulse-alarm
The rapid changes in one's pulses can activate alarms to the emergency contact, in order to ensure the user's safety. 

Instructions:

1. Open alarm.py

2. Click Run in Module to start the emulator

3. Connect GPIO pin18 to Buzzer, pin21 to Button, and pin24 to red LED 

4. Connect Sensor to Pulse

5. Scroll the Pulse Sensor left and right to initialize the pulse (bpm). 

6. Press Button1 to start monitoring
	- The Python Shell should print "Start measuring your resting heart rate..."
	- After 2 minutes, the Python Shell should start printing data

7. Adjust the pulse

8. If Python Shell prints "Buzzer and red LED is on...", press Button1 to continue the program

9. If the pulse is set to 30 bpm, the program will eventually stop
	- Rolling average of heart rate (bpm) vs. time (s) graph will pop up

10. Open alarm.txt
	- This text file contains the datasets required from the stimulation
