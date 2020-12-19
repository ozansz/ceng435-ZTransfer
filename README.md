# ZTransfer Reliable Transfer Over TCP/UDP

> ZTransfer is a reliable file transfer protocol and PoC program developed by Ozan Sazak for CENG435 THE2 Homework.

## Getting Started
### Requirements

- Python 3.6+

### Dependencies

> This project uses Python3.6's standard library, no extra dependencies exist.

### Folder Structure

- src
    - client - Client specific implementations
        - tcp.py - ZTransferTCPClient TCP client handler class impl
        - udp.py - ZTransferUDPClient UDP client handler class impl
    - server - Server specific implementations
        - tcp.py - ZTransferTCPServer TCP server handler class impl
        - udp.py - ZTransferUDPServer UDP server handler class impl
    - ztransfer - ZTransfer specifications
        - errors.py - Error codes (Mostly verification)
        - packets.py - ZTransfer packet definitions
        - profiler.py - Runtime packet transfer profiler
    - config.json - Configuration file
    - config.py - Configuration file handler
    - utils.py - Utilities that used by `cli.py`
- cli.py - Command line interface to explicitly run TCP/UDP server/client programs
- client.py - Wrapper script that calls TCP client and UDP client sequentially
- server.py - Wrapper script that calls TCP server and UDP server sequentially

## Report

> The other bullet point questions from the HW doc are answered in different sections of this README.
### Planning

I've planned this project throuh these phases:

- RDT algorithm design
- ZTransfer packets design
- TCP server/client implementation
- TCP server/client tests
- UDP server/client implementation
- UDP server/client tests
- Overall simulations

### Encountered Problems

The most significant problem i've struggled with is that in different systems, the optimal window size changes irrationally and unexpecedly. Below is a little benchmark (with 40M random-generated data) of mine in my PC (8G RAM, i5 Processor):

| Window Size | UDP Total Transfer Time |
|-------------|-------------------------|
| 2000        | 1:22.89 mins            |
| 1500        | 1:22.74 mins            |
| 1000        | 2.387 secs              |
| 500         | 2.327 secs              |
| 250         | 2.487 secs              |

To overcome this probem, i've implemented `Additive Increase Multiplicative Decrease` algorithm with 25 window size starting size, +10 in step up ans /2 in step down. This solution has worked pretty well in my design.

### It took..

3 full days (~25 hrs)

### I have learned...

That first algorithm and packet design phases are trivially important and a bad design choice can easily lead the system to need of redesign.

## RDT Design

ZTransfer uses a modified version of RDT 3.0 with pipeline impl. of Selective Repeat. Instead of waiting all window packets to be received by the receiver, it sends the packets and recvs ACKs rapidly.

### ZTransfer Packets

#### ZHeader

|      Field      | Size (Bytes) |           Description          |
|:---------------:|:------------:|:------------------------------:|
|      magic      |       2      |              b"ZT"             |
|      pytpe      |       1      |   CREQ, DATA, ACK, FIN, RSND   |
|     version     |       1      |        ZTransfer version       |
|    timestamp    |       8      |    UNIX timestamp as double    |
| sequence number |       4      |     32 bit sequence number     |
|     checksum    |       4      | CRC32 checksum of whole packet |

#### Connection Request Packet (CREQ)

|      Field      | Size (Bytes) |           Description          |
|:---------------:|:------------:|:------------------------------:|
|      ZHeader    |       20     |                                |
|      data size  |       4      |   File size as bytes           |
|     last seq#   |       4      |        last sequence number    |
|    timestamp    |       8      |    UNIX timestamp as double    |
|    filename     |       255    |     File name as string        |
|     checksum    |       4      |   SHA3-512 file oveall chksum  |

#### Data Packet (DATA)

|      Field      | Size (Bytes) |           Description          |
|:---------------:|:------------:|:------------------------------:|
|      ZHeader    |       20     |                                |
|      raw data   |       980    |   raw file data chunk          |

#### ACK Packet (ACK)

|      Field      | Size (Bytes) |           Description          |
|:---------------:|:------------:|:------------------------------:|
|      ZHeader    |       20     |                                |
|      seq to ack |       4      |   DATA packet seq number to ACK          |

#### Resend Packet (RSND)

|      Field      | Size (Bytes) |           Description          |
|:---------------:|:------------:|:------------------------------:|
|      ZHeader    |       20     |                                |
|      seq to rsnd |       4      |   DATA packet seq number to RSND          |

#### Finish Packet (FIN)

|      Field      | Size (Bytes) |           Description          |
|:---------------:|:------------:|:------------------------------:|
|      ZHeader    |       20     |                                |

### RDT FSMs

#### Server


#### Client