---
title: "Swayam"
url: "https://en.wikipedia.org/wiki/Swayam"
pageid: 45471200
revid: 1376752165
last_edited: "2026-09-26T01:34:33Z"
short_description: "Indian CubeSat"
wikidata_id: "Q19898552"
found_in_category: "CubeSats of India"
wikipedia_categories: ["CubeSats of India", "Spacecraft launched by India in 2016", "Student satellites"]
keywords: ["swayam", "subsystem", "earth magnetic", "thermal system", "terminal node", "node controller", "materials like", "hysteresis rods", "ham band", "dynamic behaviour"]
source: "Wikipedia"
license: "CC BY-SA 4.0"
fetched_at: "2026-11-05T17:01:36Z"
---

# Swayam

_Indian CubeSat_

Swayam is a 1-U picosatellite (CubeSat) developed by the undergraduate students of College of Engineering, Pune. They have successfully completed assembly of the flight model having a size of 1-U and weight of 990 grams under the guidance of Indian Space Research Organisation (ISRO) in January 2015. The structural design of the satellite, design of its electronic and control systems as well as the manufacturing of the satellite was carried out by the students. The project was completed over a span of 8 years and more than 200 students worked on it. The Satellite was launched by ISRO on June 22, 2016, along with Cartosat-2C by Polar Satellite Launch Vehicle C-34 from the second launch pad at Satish Dhawan Space Center, Sriharikota, India. The satellite is to be placed in low Earth orbit (LEO) around Earth at a height of 515 km.

The payload of the satellite is point-to-point packet communication with which a user can send and receive messages from one point to other point on the earth. The scientific objective of the satellite is to demonstrate passive attitude control to stabilise and appropriately orient the satellite. This technique is being used for the first time on an Indian Satellite. Another objective is to provide low-earth-orbit channel characterisation in the UHF ham band.

## About the programme

Mission Swayam is the first satellite project of COEP's Satellite Initiative under the CSAT programme. The team consists of students from freshers to seniors and spans all the engineering disciplines in the college. The project is in a true sense an interdisciplinary project. The students in this team are selected after a rigorous selection process. In addition to the academic work the team members dedicatedly work on this project all year round to meet the project deadlines. The team can proudly claim to have published more than 15 research papers in international conferences for last 7 consecutive years.

## Subsystems

The Satellite team is divided broadly into five subsystems.

### Attitude control system

The attitude control system (ACS) controls the dynamic behaviour of satellite like orientation and motion of satellite. In Swayam, the technique of passive magnetic attitude control system (PMACS) is implemented for the first time on an Indian satellite. The uniqueness of the technique is that it controls the orientation of the satellite without any power consumption with reasonable accuracy for communication. It is the scientific mission of the satellite to prove that PMACS is a robust and cost-effective solution for attitude control.

The primary objective of ACS is to attain a configuration favourable for communication to take place. Earth's magnetic field will be used for achieving this. Components of passive ACS include permanent magnets and hysteresis rods. The hysteresis rods are soft magnetic materials which damp the angular oscillations of the satellite and the magnet aligns the antenna along the earth's magnetic field.

To evaluate the attitude behaviour of the satellite in the orbit, the space conditions and dynamic behaviour of the satellite have been simulated through a self-developed software. From the simulation results it has been observed that, the stabilization of the satellite to the prescribed orientation, i.e. antenna along Earth's magnetic field, takes around 15 to 20 days.

ACS uses a MEMS gyroscope for stabilisation detection. Using the data from gyro sensor, the on-board computer declares stability of the satellite.

### Communication

The communication subsystem is responsible for enabling half-duplex communication of the satellite with various ground stations in the ham band of 434–438 MHz which is used both for up-linking and down-linking data. The frequency used by satellite will be 437.025 MHz. The communication subsystem can be subdivided further into two parts:

#### Spacecraft

The subsystem consists of:

- Amplifiers: Low-noise amplifier (LNA) & high-power amplifier (HPA) to amplify the received signal and the output signal respectively.
- Antenna: A dipole antenna
- Transceiver: Texas Instruments' CC1120 RF transceiver
- Terminal node controller: Microchip's PIC microcontroller, which is interfaced with the transceiver.

#### Ground station segment

The team has established a fully functional ground station in the premises with uplink and downlink capability in both the 435 MHz as well as the 145 MHz bands. The team has successfully received signals from various analog and digital satellites and the data has been verified from the respective satellite teams. The ground segment includes an array of two crossed Yagi antennas for the 434-438 MHz band and a simple Yagi Uda and potato masher antenna for the 144–148 MHz range.

### Onboard computer

The onboard computer (OC) subsystem is a fault tolerant microcontroller based system. The microcontroller used is AT91SAM7x512. It is the second subsystem to start after power and plays a major role in antenna deployment. Over the course of the mission, OC collects crucial data about the health of the various systems within the satellite and stores it in a non-volatile memory, only to be sent to the ground station on request. It also manages the payload of point to point communication by storing and sending messages appropriately. The major role of OC relies in handling the set of commands received from the ground stations through the communication system. OC is the master control system of the satellite.

### Power

The Power Subsystem is completely analog in nature and also fully autonomous in its functioning, being the first subsystem to start up after the launch. It provides power to all the electrical systems on board the satellite and protects them from electrical faults. DC-DC converters are used for conditioning and regulation of power. Load protection circuits are designed for triple redundancy and work in coordination with the onboard computer and terminal node controller. The power system is responsible for the deployment of the antenna for the communication system through a surge of current. Li-ion batteries are used for energy storage. On-board voltage, current, and temperature sensors monitor electrical and thermal status of the satellite and provide a critical part of health monitoring data (HMD).

### Structure

The structure subsystem is responsible for providing a robust body for the satellite which can house all the components and protect them from the harsh conditions of space. Comparative studies of different materials revealed that Al 6061-T6 is better suited. Hence it has been used for the main frame of the satellite. Other materials like ABS, FR4 have also been used as per the specific requirements. All these materials were first tested for their properties before being put into use. The main structure of the satellite consists of four rails and two frames. Three PCB's are arranged in a U deck, with the battery pack in the middle.

Vibration analysis: During launch, the satellite undergoes intense vibrations. It must be able to sustain these. For the same, simulations have been run and validated by performing tests on both the qualification and flight models.

Thermal management and control: Temperature of the satellite has to be maintained within a particular range in order to ensure proper functioning. A passive thermal system has been employed in Swayam. Insulating materials like kapton, white paint, low emittance tape, black tape and optical solar reflector are used. The thermal system has been put to test in the thermo vacuum test (on QM and FM) and hot and cold test (on QM).

## Achievements

The team has published and presented various papers in various conferences. In the year 2011, one of the founding members of this initiative, Nischay Mhatre, became the first Indian to be awarded the prestigious Luigi Napolitano Award by IAF for his publications at the International Astronautical Congress as a young scientist under the age of 30.

The Swayam satellite was also honored with the Gandhian Young Technological Innovation Award for the year 2016, under the category of Aerospace Engineering by Society for Research and Initiatives for Sustainable Technologies and Institutions.
