# Testing Checklist - Dialog Fix Verification

## Quick Test (5 minutes)

### Test 1: Input Validation Dialogs
- [ ] Try to add material without description
- [ ] **Expected**: Warning dialog appears ON TOP immediately
- [ ] **Check**: Dialog is clearly visible, not hidden

### Test 2: Confirmation Dialogs  
- [ ] Try to delete a material
- [ ] **Expected**: Confirmation dialog appears ON TOP
- [ ] **Check**: Can see the confirmation clearly

### Test 3: Error Messages
- [ ] Try to withdraw more than available stock
- [ ] **Expected**: Error message appears ON TOP
- [ ] **Check**: Error is immediately visible

### Test 4: Success Messages
- [ ] Add a new material successfully
- [ ] **Expected**: Success message appears ON TOP
- [ ] **Check**: Message shows material ID and is visible

### Test 5: Popup Windows
- [ ] Open "Withdrawals Dashboard"
- [ ] Try to export without data
- [ ] **Expected**: Any dialog appears ON TOP of dashboard
- [ ] **Check**: Dialog doesn't hide behind main window

## Comprehensive Test (15 minutes)

### Main Window Dialogs
- [ ] Add material - validation warnings
- [ ] Update material - success messages
- [ ] Delete material - confirmation dialog
- [ ] Search with no results - (no dialog, but test search works)
- [ ] Clear filter - (no dialog)

### Withdrawal Window
- [ ] Open withdraw window
- [ ] Try invalid quantity - error dialog on top
- [ ] Try quantity > stock - error dialog on top
- [ ] Successful withdrawal - success dialog on top
- [ ] Low stock alert - email sent (check if dialog appears)

### Receive Parts Window
- [ ] Open receive window
- [ ] Try invalid quantity - error dialog on top
- [ ] Successful receive - success dialog on top

### PR Monitoring Window
- [ ] Open PR monitoring
- [ ] Try to add PR with invalid data - error dialog on top
- [ ] Edit PR - dialog appears on top
- [ ] Delete PR - confirmation on top

### Low Stock Dashboard
- [ ] Open low stock dashboard
- [ ] Double-click to edit remarks - edit box appears
- [ ] Export to CSV - file dialog appears on top

### Assembly Manager (Admin Only)
- [ ] Open assembly manager
- [ ] Create new assembly - input dialog on top
- [ ] Delete assembly - confirmation on top
- [ ] Add part to assembly - selection dialog on top

### User Management (Admin Only)
- [ ] Open manage users
- [ ] Create user - validation messages on top
- [ ] Delete user - confirmation on top
- [ ] Reset password - input dialog on top
- [ ] Change role - input dialog on top

### Change Password
- [ ] User menu → Change Password
- [ ] Try wrong current password - error on top
- [ ] Try mismatched passwords - warning on top
- [ ] Successful change - success message on top

### Login Screen
- [ ] Try wrong password - error dialog on top
- [ ] Try empty fields - warning on top
- [ ] Successful login - (no dialog)

## Multi-Window Test

### Test Scenario: Multiple Windows Open
1. [ ] Open main window
2. [ ] Open "Withdrawals Dashboard"
3. [ ] Open "PR Monitoring"
4. [ ] Try to trigger error in PR Monitoring
5. [ ] **Expected**: Error appears on top of PR window, not hidden
6. [ ] Close PR Monitoring
7. [ ] Try to trigger error in Withdrawals Dashboard
8. [ ] **Expected**: Error appears on top of dashboard window

## Edge Cases

### Test: Rapid Dialog Triggering
- [ ] Quickly click "Add" multiple times without filling description
- [ ] **Expected**: Each warning appears on top, doesn't stack weirdly

### Test: Dialog While Another Dialog Open
- [ ] Open a dialog (e.g., withdraw window)
- [ ] Trigger another dialog (e.g., validation error)
- [ ] **Expected**: New dialog appears on top of first dialog

### Test: Minimize and Restore
- [ ] Open main window
- [ ] Minimize it
- [ ] Restore it
- [ ] Trigger a dialog
- [ ] **Expected**: Dialog appears on top of restored window

## Performance Check

### Before and After Comparison
- [ ] Note: First run after update may be slower (creating indexes)
- [ ] Subsequent runs should be faster
- [ ] Search should feel snappier
- [ ] Low stock sync should be faster

## Visual Verification

### Dialog Appearance
- [ ] Dialogs are centered on screen
- [ ] Dialogs have proper focus (can type immediately)
- [ ] Dialogs don't flicker or flash
- [ ] Parent window returns to focus after dialog closes

## Regression Testing

### Ensure Nothing Broke
- [ ] All buttons still work
- [ ] All menus still work
- [ ] Data loads correctly
- [ ] Search works (now searches more fields!)
- [ ] Export functions work
- [ ] Email notifications work
- [ ] Database operations work

## Sign-Off

**Tester Name**: ___________________
**Date**: ___________________
**Result**: ☐ Pass ☐ Fail ☐ Pass with Notes

**Notes**:
_____________________________________________
_____________________________________________
_____________________________________________

**Issues Found**:
_____________________________________________
_____________________________________________
_____________________________________________

---

## Quick Reference: What Changed

✅ **100 dialog calls** now use new helper functions
✅ **All dialogs** stay on top of their parent windows
✅ **Better focus** management
✅ **No breaking changes** - everything else works the same

## If You Find Issues

1. Note which dialog is problematic
2. Note which window it should appear on top of
3. Check if it's a new window or main window
4. Report with steps to reproduce

---

**Expected Result**: All dialogs should appear immediately on top and be clearly visible. No more hunting for hidden dialogs!
