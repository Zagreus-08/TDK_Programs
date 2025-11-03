"""
Utility functions for MCC DAQ HAT examples
"""

def chan_list_to_mask(chan_list):
    """
    Convert a list of channel numbers to a channel mask.
    
    Args:
        chan_list: A list of channel numbers (e.g., [0, 1, 2])
        
    Returns:
        An integer representing the channel mask
    """
    mask = 0
    for chan in chan_list:
        mask |= (1 << chan)
    return mask


def validate_channels(channel_set, number_of_channels):
    """
    Validate that all channels are within the valid range.
    
    Args:
        channel_set: Set of channel numbers
        number_of_channels: Maximum number of channels
        
    Returns:
        True if valid, False otherwise
    """
    if not channel_set:
        return False
    
    for channel in channel_set:
        if channel < 0 or channel >= number_of_channels:
            return False
    
    return True


def enum_mask_to_string(enum_class, bit_mask):
    """
    Convert a bit mask to a string of enum names.
    
    Args:
        enum_class: The enum class
        bit_mask: The bit mask value
        
    Returns:
        A string of enum names separated by ' | '
    """
    items = []
    for item in enum_class:
        if item.value & bit_mask:
            items.append(item.name)
    
    if not items:
        items.append('DEFAULT')
    
    return ' | '.join(items)
