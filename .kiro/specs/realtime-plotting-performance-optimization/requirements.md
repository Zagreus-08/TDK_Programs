# Requirements Document

## Introduction

This document specifies requirements for optimizing the real-time data plotting system between two Raspberry Pi devices. The current system experiences significant lag during visualization due to inefficient data transmission, lack of buffering, and expensive rendering operations performed at high frequency. The optimization will reduce plotting lag while maintaining data accuracy and visual quality for scans ranging from 100x100mm to 300x300mm areas with 2000-6000 data points.

## Glossary

- **Scanner_Pi**: The Raspberry Pi running V6_Mini_XY_Scanner.py that controls XY scanning movement and collects sensor data
- **Plotter_Pi**: The Raspberry Pi running Nivio-S_Realtime_Plotter.py that receives serial data and performs real-time visualization
- **Data_Point**: A single measurement consisting of X position (mm), Y position (mm), and Z value (voltage)
- **Serial_Link**: The 115200 baud serial connection between Scanner_Pi and Plotter_Pi
- **Interpolation**: The griddata() cubic interpolation operation that generates a smooth surface from discrete data points
- **Rendering_Cycle**: A complete update of the matplotlib visualization including 2D heatmap and 3D surface plot
- **Data_Buffer**: A collection of accumulated Data_Points waiting to be processed
- **Update_Interval**: The time period between consecutive Rendering_Cycles (currently 250ms)
- **Data_Interval**: The time period between consecutive Data_Point transmissions from Scanner_Pi (currently 50ms)
- **Downsampling**: The process of reducing the number of Data_Points by selecting a representative subset
- **Batch_Transmission**: Sending multiple Data_Points in a single serial message
- **Incremental_Rendering**: Updating only changed portions of the visualization rather than full redraw

## Requirements

### Requirement 1: Serial Data Transmission Optimization

**User Story:** As a system operator, I want efficient data transmission between Scanner_Pi and Plotter_Pi, so that the serial link does not become a bottleneck during scanning.

#### Acceptance Criteria

1. WHEN Scanner_Pi has accumulated 5 or more Data_Points, THE Scanner_Pi SHALL transmit them as a Batch_Transmission via Serial_Link
2. THE Batch_Transmission SHALL use a compact format with comma-separated values and newline delimiters
3. WHEN Plotter_Pi receives a Batch_Transmission, THE Plotter_Pi SHALL parse all Data_Points and append them to Data_Buffer
4. THE Serial_Link SHALL maintain 115200 baud rate for compatibility with existing hardware
5. WHEN Scanner_Pi buffer contains fewer than 5 Data_Points at scan completion, THE Scanner_Pi SHALL transmit remaining Data_Points immediately

### Requirement 2: Data Buffering and Downsampling

**User Story:** As a system operator, I want intelligent data management on Plotter_Pi, so that visualization performance remains smooth even with thousands of data points.

#### Acceptance Criteria

1. WHEN Data_Buffer contains more than 1000 Data_Points, THE Plotter_Pi SHALL apply Downsampling to reduce the dataset to approximately 800 Data_Points
2. THE Downsampling SHALL preserve data points with maximum and minimum Z values within each spatial region
3. THE Downsampling SHALL divide the scan area into a uniform grid and select representative Data_Points from each grid cell
4. WHEN a scan is complete, THE Plotter_Pi SHALL retain all original Data_Points for final high-resolution rendering
5. THE Data_Buffer SHALL store Data_Points in a numpy array for efficient memory access

### Requirement 3: Adaptive Rendering Frequency

**User Story:** As a system operator, I want the visualization update rate to adapt to system load, so that plotting remains responsive without overwhelming the Raspberry Pi.

#### Acceptance Criteria

1. WHEN Data_Buffer contains fewer than 100 Data_Points, THE Plotter_Pi SHALL set Update_Interval to 500ms
2. WHEN Data_Buffer contains 100 to 500 Data_Points, THE Plotter_Pi SHALL set Update_Interval to 350ms
3. WHEN Data_Buffer contains more than 500 Data_Points, THE Plotter_Pi SHALL set Update_Interval to 250ms
4. WHEN a Rendering_Cycle takes longer than Update_Interval, THE Plotter_Pi SHALL skip the next scheduled update
5. THE Plotter_Pi SHALL measure actual Rendering_Cycle duration and log warnings when duration exceeds 200ms

### Requirement 4: Optimized Interpolation Strategy

**User Story:** As a system operator, I want efficient surface interpolation, so that the griddata() operation does not cause excessive lag.

#### Acceptance Criteria

1. WHEN Data_Buffer contains fewer than 200 Data_Points, THE Plotter_Pi SHALL use cubic interpolation method
2. WHEN Data_Buffer contains 200 or more Data_Points, THE Plotter_Pi SHALL use linear interpolation method
3. THE Interpolation SHALL operate on a fixed 50x50 grid resolution regardless of scan area size
4. WHEN consecutive Rendering_Cycles occur within 1 second, THE Plotter_Pi SHALL reuse the previous interpolation grid
5. THE Plotter_Pi SHALL cache interpolation results and invalidate cache only when new Data_Points are added

### Requirement 5: Incremental Visualization Updates

**User Story:** As a system operator, I want efficient plot updates, so that the matplotlib rendering does not require full figure recreation every cycle.

#### Acceptance Criteria

1. THE Plotter_Pi SHALL create matplotlib figure and axes objects once at initialization
2. WHEN updating visualization, THE Plotter_Pi SHALL clear only the contour and surface plot data
3. THE Plotter_Pi SHALL reuse existing colorbar objects rather than recreating them
4. THE Plotter_Pi SHALL update plot data using set_data() methods rather than recreating plot objects
5. WHEN scan is complete, THE Plotter_Pi SHALL perform one final full-resolution rendering with all original Data_Points

### Requirement 6: Reduced Contour Levels

**User Story:** As a system operator, I want appropriate contour detail, so that rendering performance is balanced with visual quality.

#### Acceptance Criteria

1. WHEN Data_Buffer contains fewer than 500 Data_Points, THE Plotter_Pi SHALL render 2D heatmap with 32 contour levels
2. WHEN Data_Buffer contains 500 or more Data_Points, THE Plotter_Pi SHALL render 2D heatmap with 64 contour levels
3. THE 3D surface plot SHALL use a stride value of 2 for reduced polygon count
4. WHEN scan is complete, THE Plotter_Pi SHALL render final visualization with 128 contour levels
5. THE contour level count SHALL be configurable via a parameter in the Plotter_Pi configuration

### Requirement 7: Performance Monitoring and Diagnostics

**User Story:** As a system operator, I want visibility into system performance, so that I can identify bottlenecks and verify optimization effectiveness.

#### Acceptance Criteria

1. THE Plotter_Pi SHALL measure and display average Rendering_Cycle duration every 10 cycles
2. THE Plotter_Pi SHALL count and display total Data_Points received per second
3. WHEN Rendering_Cycle duration exceeds 300ms, THE Plotter_Pi SHALL log a warning with timing breakdown
4. THE Plotter_Pi SHALL display current Data_Buffer size in the GUI status bar
5. THE Plotter_Pi SHALL log serial transmission errors and data parsing failures with timestamps

### Requirement 8: Backward Compatibility

**User Story:** As a system operator, I want the optimized system to work with existing hardware and saved data, so that no equipment replacement is required.

#### Acceptance Criteria

1. THE optimized Plotter_Pi SHALL accept both single Data_Point and Batch_Transmission formats via Serial_Link
2. THE optimized Plotter_Pi SHALL load and display CSV files saved by the previous system version
3. THE Scanner_Pi SHALL maintain the existing GPIO pin configuration and stepper motor control
4. THE optimized system SHALL preserve the existing scan coordinate system with origin at top-right
5. THE optimized system SHALL save CSV files in the same format as the previous system version

### Requirement 9: Configuration and Tuning

**User Story:** As a system operator, I want adjustable performance parameters, so that I can tune the system for different scan scenarios.

#### Acceptance Criteria

1. THE Plotter_Pi SHALL load performance parameters from a configuration file at startup
2. THE configuration file SHALL specify Update_Interval, downsampling threshold, and contour level values
3. WHEN configuration file is missing, THE Plotter_Pi SHALL use default parameter values
4. THE Plotter_Pi SHALL validate configuration parameters and reject values outside safe ranges
5. THE Scanner_Pi SHALL load batch size parameter from configuration file with default value of 5

### Requirement 10: Memory Management

**User Story:** As a system operator, I want efficient memory usage, so that the Raspberry Pi does not run out of memory during long scans.

#### Acceptance Criteria

1. THE Plotter_Pi SHALL store Data_Points in numpy arrays with pre-allocated capacity
2. WHEN Data_Buffer exceeds 10000 Data_Points, THE Plotter_Pi SHALL log a warning
3. THE Plotter_Pi SHALL release matplotlib figure memory when loading a new scan
4. THE Plotter_Pi SHALL monitor available system memory and log warnings when free memory drops below 100MB
5. THE Plotter_Pi SHALL clear cached interpolation results when Data_Buffer is cleared
