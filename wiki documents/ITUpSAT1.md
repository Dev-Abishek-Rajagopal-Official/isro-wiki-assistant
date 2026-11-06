---
title: "ITUpSAT1"
url: "https://en.wikipedia.org/wiki/ITUpSAT1"
pageid: 24455487
revid: 1352754298
last_edited: "2026-05-06T02:22:54Z"
short_description: "Turkish CubeSat satellite"
wikidata_id: "Q5975034"
found_in_category: "Spacecraft launched by PSLV rockets"
wikipedia_categories: ["Istanbul Technical University", "Student satellites", "CubeSats", "Spacecraft launched in 2009", "Earth observation satellites of Turkey", "Spacecraft launched by PSLV rockets"]
keywords: ["pumpkin inc", "microhard systems", "microcontroller", "video graphics", "msp430f1611 microcontroller", "low-resolution cmos", "istanbul technical", "i2c bus", "graphics array", "flight module"]
source: "Wikipedia"
license: "CC BY-SA 4.0"
fetched_at: "2026-11-05T16:56:00Z"
---

# ITUpSAT1

_Turkish CubeSat satellite_

ITUpSAT1, short for Istanbul Technical University picoSatellite-1, is a single CubeSat built by the Faculty of Aeronautics and Astronautics at the Istanbul Technical University. It was launched on 23 September 2009 atop a PSLV-C14 satellite launch vehicle from Satish Dhawan Space Centre, Sriharikota, Andhra Pradesh in India, and became the first Turkish university satellite to orbit the Earth. It was expected to have a minimum of six-month life term, but it is still functioning for over two years. It is a picosatellite with side lengths of 10 centimetres (3.9 in) and a mass of 0.990 kilograms (2.18 lb).

The overall objectives are to provide a hands-on project environment for the students at the ITU under faculty guidance. The mission goals are to capture imagery of the CMOS payload, and to study the behavior of the passive stabilisation system of the CubeSat.

## Key facts

- Mission type: Earth observation
- Operator: Faculty of Aeronautics and Astronautics, Istanbul Technical University
- COSPAR ID: 2009-051E
- SATCAT no.: 35935
- Website: http://usl.itu.edu.tr/usl.itu.edu.tr
- Mission duration: 6 months
- **Spacecraft properties**
- Manufacturer: Pumpkin Inc.
- Launch mass: 990 g
- **Start of mission**
- Launch date: 23 September 2009
- Rocket: PSLV-C14
- Launch site: Satish Dhawan, FLP
- Contractor: Indian Space Research Organisation
- **Orbital parameters**
- Reference system: Geocentric
- Regime: Sun-synchronous
- Perigee altitude: 712.0 km
- Apogee altitude: 721.0 km
- Inclination: 98.28°
- Period: 98.50 minutes
- Epoch: 23 September 2009

## Spacecraft

The spacecraft structure was purchased from Pumpkin Inc. of San Francisco, California, consisting of aluminium 6061 and 5052 material (CubeSat Kit by Pumpkin Inc.). There are three identical side faces and one face with access ports. The spacecraft stabilisation concept is discussed under Payload.

### Electrical power subsystem

The electrical power subsystem consists of face-mounted solar panels, a regulator board and associated batteries. The system is able to charge itself (maximum power point tracking) and provide a regulated 3.3 V and 5 V bus service.

Design of a deployable antenna system for a CubeSat, after investigating of various alternatives. The pin mechanism selected includes bases to attach the antennas and pins to wrap them around. The pins and bases are attached to the solar panels with small screws. The cables are routed to a connector outside for connection to the antennas.

### On-board computer

The FM430 flight module of Pumpkin Inc. is being used. The FM430 is a compact solution for harsh environment systems. It has an SD (Secure Digital) card interface, one Universal Serial Bus (USB) port and external power supply connector. Also an interface to MHX series radio modems from Microhard Systems is available on the flight module. The FM430 is equipped with an MSP430F1611 microcontroller, a 16 bit 8 MHz low power microcontroller from Texas Instruments. It has many peripherals such as I2C (Inter-Integrated Communication), SPI (Serial Peripheral Interface), UART (Universal Asynchronous Receiver/Transmitter) buses, and also supports DMA (Direct Memory Access). It has a flash memory of 55 kB and 10 kB of RAM. The microcontroller unit consumes 100 mW of power at most.

### RF communications

The primary on-board communication system is the MHX-425 transceiver from Microhard Systems. This frequency hopping spread spectrum radio, which works in the UHF band has adjustable hopping patterns, a high sensitivity (-115 dBm), and output power of up to 1 W (437.325 MHz, GFSK modulation), the data rate is 19.2 kbit/s. The transceiver interfaces directly to the on-board computer, it has a mass of about 80 gram.

In addition, ITUpSat-1 features a beacon for easy identification and continuous reporting of critical telemetry. Unlike the other transceiver, it always be on during the orbit, and be transmitting identification and simple telemetry in CW (e.g. Morse code) every two minutes. This means anyone with the knowledge of the orbital parameters (in particular the amateur radio community) can easily pick up the satellite's signal. The beacon has a 100 mW RF output capacity.

## Launch

ITUpSat-1 was launched on 23 September 2009 as a secondary payload atop a PSLV launcher of ISRO (launch provider: Antrix Corporation). The SPL (Single Picosatellite Launcher) system of Astrofein (Astro und Feinwerktechnik Adlershof GmbH, Berlin, Germany) is being used to deploy the four CubeSats. The launch service interface for all CubeSats is provided by ISIS (Innovative Solutions In Space BV) from Delft, Netherlands.

The launch site is the SDSC‐SHAR (Satish Dhawan Space Centre, Sriharikota) on the east coast of India. The primary payload on the flight was Oceansat-2 of ISRO (Indian Space Research Organisation) with a launch mass of 960 kg. Further secondary payloads on this flight were:

- BeeSat-1 (Berlin Experimental Educational Satellite), a CubeSat of the TUB (Technische Universität Berlin), Berlin, Germany
- UWE-2 (University of Würzburg Experimentalsatellit-2), Würzburg, Germany
- SwissCube, a CubeSat of École Polytechnique Fédérale de Lausanne, Lausanne, Switzerland
- Rubin-9.1 and Rubin-9.2 nanosatellites of OHB-System, Bremen, Germany.

## Orbit

Sun-synchronous near circular orbit at altitude of 720 kilometres (450 mi), inclination is 98.28°, orbital period 98.50 minutes, the local equatorial crossing time is at 12:00 hours.

## Payloads

### Sensor complement

The CubeSat features two payloads. The first one is a sensor suite with an IMU and a magnetometer, and the second one is a low-resolution CMOS imager. The two payloads share a microcontroller and are physically on the same PCB representing the uppermost circuit of the electronics stack of the satellite.

### Payload #1

This subsystem represents the attitude sensing and passive stability hardware. It consists of three gyros, a three-axis accelerometer both from Analog Devices in addition to a three-axis magnetometer (Honeywell), and an Alnico magnet. The magnetometer will help to counter the inherent bias and drifts of inertial sensors and provide measurement updates for a filtered and corrected solution of the attitude. The analog-digital conversion of all the sensor outputs is done by a PIC microprocessor which also has the task of grouping the measurements into a packet and sending them over the I2C bus to the on-board computer for downlink transmission.

### Payload #2

Payload #2 is a low-resolution CMOS camera with a detector array of 640 x 480 pixels (COTS imager based on the OV7620 image sensor). The objective is to take snapshot imagery. An interface board is designed to integrate camera with the MSP430F1611 microcontroller.

The camera can be operated in VGA/QVGA (Video Graphics Array/Quarter Video Graphics Array) modes, transfer images in 8/16 bit modes and can be controlled over the I2C bus.

## Ground segment

A ground station was built at the ITU for the operations (monitoring and control services) of ITUpSat-1. The MHX modem (Microhard Systems) is also installed in the ground station for communication with the satellite's nominal communication system.
