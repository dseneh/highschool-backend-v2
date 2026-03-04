# Gradebook API Guide

Complete guide to using the Gradebook API, including the GradingTaskStatusView.

---

## 📋 Table of Contents

1. [Endpoints Overview](#endpoints-overview)
2. [Updating Grading Settings](#updating-grading-settings)
3. [Background Task Workflow](#background-task-workflow)
4. [GradingTaskStatusView Usage](#gradingtaskstatusview-usage)
5. [Response Examples](#response-examples)
6. [Error Handling](#error-handling)
7. [Frontend Integration](#frontend-integration)

---

## Endpoints Overview

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/settings/{school_id}/grading/` | GET | Get grading settings |
| `/api/v1/settings/{school_id}/grading/` | PATCH | Update grading settings |
| `/api/v1/settings/{school_id}/grading-style/` | GET | Get current grading style |
| `/api/v1/settings/{school_id}/grading/tasks/{task_id}/` | GET | Check task status |
| `/api/v1/settings/{school_id}/grading/tasks/{task_id}/` | DELETE | Cancel task |

---

## Updating Grading Settings

### Endpoint
```
PATCH /api/v1/settings/{school_id}/grading/
```

### Request Headers
```
Content-Type: application/json
Authorization: Bearer <token>
```

### Request Body
```json
{
  "grading_style": "single_entry",  // or "multiple_entry"
  "force": true                      // Required if changing grading_style
}
```

### Parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `grading_style` | string | Yes | Either "single_entry" or "multiple_entry" |
| `force` | boolean | Conditional | Required when changing grading_style (triggers reinitialization) |

### Response Scenarios

#### Scenario 1: Small School (Synchronous - < 50 sections)

**Response**: HTTP 200 OK
```json
{
  "success": true,
  "message": "Grading settings updated successfully",
  "is_async": false,
  "data": {
    "id": "uuid",
    "grading_style": "single_entry",
    "updated_at": "2025-11-01T10:30:00Z"
  },
  "grading_style_changed": true,
  "old_grading_style": "multiple_entry",
  "new_grading_style": "single_entry",
  "reinitialization": {
    "performed": true,
    "all_succeeded": true,
    "total_gradebooks_created": 150,
    "total_assessments_created": 600,
    "total_grades_created": 4500,
    "results": [
      {
        "academic_year": {
          "id": "uuid",
          "name": "2024-2025"
        },
        "success": true,
        "message": "Gradebooks initialized successfully",
        "stats": {
          "gradebooks_created": 150,
          "assessments_created": 600,
          "grades_created": 4500
        }
      }
    ]
  }
}
```

**Processing**: Completed immediately (2-5 seconds)
**Action**: Settings are updated and ready to use

---

#### Scenario 2: Large School (Asynchronous - ≥ 50 sections)

**Response**: HTTP 202 ACCEPTED
```json
{
  "success": true,
  "message": "Gradebook initialization started in background",
  "is_async": true,
  "task_id": "a3f7c8e9-1234-5678-9abc-def012345678",
  "status_url": "/api/v1/settings/abc123/grading/tasks/a3f7c8e9-1234-5678-9abc-def012345678/",
  "estimated_time_seconds": 200,
  "section_count": 100,
  "grading_style_change": {
    "old": "multiple_entry",
    "new": "single_entry"
  },
  "note": "Settings will be updated automatically after successful initialization. Check status_url for progress."
}
```

**Processing**: Background task started
**Action**: Poll `status_url` for completion

---

## Background Task Workflow

### Step-by-Step Process

```
1. Send PATCH request
         ↓
2. Receive 202 ACCEPTED with task_id
         ↓
3. Poll GET /tasks/{task_id}/ every 2-3 seconds
         ↓
4. Monitor progress (0-100%)
         ↓
5. Wait for status: "completed"
         ↓
6. Settings are automatically updated
         ↓
7. Use new grading style
```

### Polling Example

```javascript
async function updateGradingStyle(schoolId, newStyle) {
  // Step 1: Initiate change
  const response = await fetch(
    `/api/v1/settings/${schoolId}/grading/`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        grading_style: newStyle,
        force: true
      })
    }
  );
  
  const data = await response.json();
  
  // Step 2: Check if async
  if (data.is_async) {
    const taskId = data.task_id;
    
    // Step 3: Poll for status
    return await pollTaskStatus(schoolId, taskId);
  } else {
    // Synchronous - already complete
    return data;
  }
}

async function pollTaskStatus(schoolId, taskId) {
  const statusUrl = `/api/v1/settings/${schoolId}/grading/tasks/${taskId}/`;
  
  while (true) {
    const response = await fetch(statusUrl);
    const task = await response.json();
    
    console.log(`Progress: ${task.progress}% - ${task.message}`);
    
    if (task.status === 'completed') {
      return task.result;
    }
    
    if (task.status === 'failed') {
      throw new Error(task.error);
    }
    
    // Wait 2 seconds before next poll
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}
```

---

## GradingTaskStatusView Usage

### Get Task Status

#### Endpoint
```
GET /api/v1/settings/{school_id}/grading/tasks/{task_id}/
```

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `school_id` | string | School ID, ID number, or workspace |
| `task_id` | string | UUID of the background task |

#### Response Formats

##### Status: Pending
```json
{
  "success": true,
  "task_id": "a3f7c8e9-1234-5678-9abc-def012345678",
  "status": "pending",
  "progress": 0,
  "message": "Task is queued and waiting to start",
  "created_at": "2025-11-01T10:30:00Z",
  "updated_at": "2025-11-01T10:30:00Z"
}
```

##### Status: Processing
```json
{
  "success": true,
  "task_id": "a3f7c8e9-1234-5678-9abc-def012345678",
  "status": "processing",
  "progress": 45,
  "message": "Task is currently processing",
  "created_at": "2025-11-01T10:30:00Z",
  "updated_at": "2025-11-01T10:31:30Z"
}
```

##### Status: Completed
```json
{
  "success": true,
  "task_id": "a3f7c8e9-1234-5678-9abc-def012345678",
  "status": "completed",
  "progress": 100,
  "message": "Task completed successfully",
  "created_at": "2025-11-01T10:30:00Z",
  "updated_at": "2025-11-01T10:33:00Z",
  "result": {
    "success": true,
    "message": "Gradebooks initialized successfully",
    "stats": {
      "gradebooks_created": 600,
      "assessments_created": 3000,
      "grades_created": 105000
    }
  },
  "settings_updated": true,
  "new_grading_style": "single_entry"
}
```

##### Status: Failed
```json
{
  "success": true,
  "task_id": "a3f7c8e9-1234-5678-9abc-def012345678",
  "status": "failed",
  "progress": 0,
  "message": "Task failed",
  "created_at": "2025-11-01T10:30:00Z",
  "updated_at": "2025-11-01T10:31:00Z",
  "error": "Database connection timeout"
}
```

##### Error: Task Not Found
```json
{
  "success": false,
  "error": "Task not found"
}
```
**HTTP Status**: 404 NOT FOUND

##### Error: Wrong School
```json
{
  "success": false,
  "error": "Task does not belong to this school"
}
```
**HTTP Status**: 403 FORBIDDEN

---

### Cancel Task

#### Endpoint
```
DELETE /api/v1/settings/{school_id}/grading/tasks/{task_id}/
```

#### Response: Success
```json
{
  "success": true,
  "message": "Task cancelled successfully"
}
```
**HTTP Status**: 200 OK

#### Response: Cannot Cancel
```json
{
  "success": false,
  "error": "Cannot cancel task with status: completed"
}
```
**HTTP Status**: 400 BAD REQUEST

**Note**: You can only cancel tasks with status "pending" or "processing"

---

## Response Examples

### Complete Flow Example

#### 1. Initial Request (Large School)
```bash
curl -X PATCH "http://localhost:8000/api/v1/settings/school123/grading/" \
  -H "Content-Type: application/json" \
  -d '{
    "grading_style": "single_entry",
    "force": true
  }'
```

**Response**:
```json
{
  "success": true,
  "is_async": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status_url": "/api/v1/settings/school123/grading/tasks/550e8400-e29b-41d4-a716-446655440000/",
  "estimated_time_seconds": 180
}
```

#### 2. Check Status (First Poll - 2 seconds later)
```bash
curl "http://localhost:8000/api/v1/settings/school123/grading/tasks/550e8400-e29b-41d4-a716-446655440000/"
```

**Response**:
```json
{
  "success": true,
  "status": "processing",
  "progress": 15,
  "message": "Task is currently processing"
}
```

#### 3. Check Status (Second Poll - 4 seconds later)
```bash
curl "http://localhost:8000/api/v1/settings/school123/grading/tasks/550e8400-e29b-41d4-a716-446655440000/"
```

**Response**:
```json
{
  "success": true,
  "status": "processing",
  "progress": 60,
  "message": "Task is currently processing"
}
```

#### 4. Final Status (Completion - 3 minutes total)
```bash
curl "http://localhost:8000/api/v1/settings/school123/grading/tasks/550e8400-e29b-41d4-a716-446655440000/"
```

**Response**:
```json
{
  "success": true,
  "status": "completed",
  "progress": 100,
  "message": "Task completed successfully",
  "result": {
    "success": true,
    "stats": {
      "gradebooks_created": 600,
      "assessments_created": 3000,
      "grades_created": 105000
    }
  },
  "settings_updated": true,
  "new_grading_style": "single_entry"
}
```

---

## Error Handling

### Common Errors

#### 1. Missing Force Parameter
**Request**:
```json
{
  "grading_style": "single_entry"
  // Missing "force": true
}
```

**Response**: HTTP 400 BAD REQUEST
```json
{
  "success": false,
  "detail": "Grading style change detected (multiple_entry → single_entry). This requires reinitializing all gradebooks. Pass \"force\": true to confirm and reinitialize gradebooks (DESTRUCTIVE: will delete existing gradebooks).",
  "warning": "This operation will DELETE all existing gradebooks, assessments, and grades!",
  "current_grading_style": "multiple_entry",
  "new_grading_style": "single_entry",
  "requires_force": true
}
```

#### 2. Invalid Grading Style
**Request**:
```json
{
  "grading_style": "invalid_style",
  "force": true
}
```

**Response**: HTTP 400 BAD REQUEST
```json
{
  "success": false,
  "detail": "Invalid grading_style value. Must be \"single_entry\" or \"multiple_entry\"."
}
```

#### 3. No Active Academic Year
**Response**: HTTP 400 BAD REQUEST
```json
{
  "detail": "No active academic years to reinitialize gradebooks for."
}
```

#### 4. Task Not Found
**Response**: HTTP 404 NOT FOUND
```json
{
  "success": false,
  "error": "Task not found"
}
```

#### 5. Initialization Failed
**Response**: HTTP 400 BAD REQUEST
```json
{
  "success": false,
  "message": "Gradebook reinitialization failed. Settings were NOT updated.",
  "grading_style_changed": false,
  "old_grading_style": "multiple_entry",
  "attempted_grading_style": "single_entry",
  "reinitialization": {
    "performed": true,
    "all_succeeded": false,
    "errors": [
      "Error reinitializing 2024-2025: Database connection lost"
    ]
  }
}
```

---

## Frontend Integration

### React Example

```javascript
import { useState, useEffect } from 'react';

function GradingStyleUpdate({ schoolId }) {
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [taskId, setTaskId] = useState(null);

  const updateGradingStyle = async (newStyle) => {
    setLoading(true);
    setError(null);
    setProgress(0);

    try {
      const response = await fetch(
        `/api/v1/settings/${schoolId}/grading/`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            grading_style: newStyle,
            force: true
          })
        }
      );

      const data = await response.json();

      if (data.is_async) {
        // Start polling
        setTaskId(data.task_id);
        pollStatus(data.task_id);
      } else {
        // Synchronous - complete
        setLoading(false);
        setProgress(100);
        alert('Grading style updated successfully!');
      }
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  };

  const pollStatus = async (taskId) => {
    const interval = setInterval(async () => {
      try {
        const response = await fetch(
          `/api/v1/settings/${schoolId}/grading/tasks/${taskId}/`
        );
        const task = await response.json();

        setProgress(task.progress);

        if (task.status === 'completed') {
          clearInterval(interval);
          setLoading(false);
          setProgress(100);
          alert('Grading style updated successfully!');
        } else if (task.status === 'failed') {
          clearInterval(interval);
          setLoading(false);
          setError(task.error);
        }
      } catch (err) {
        clearInterval(interval);
        setError(err.message);
        setLoading(false);
      }
    }, 2000); // Poll every 2 seconds
  };

  const cancelTask = async () => {
    if (!taskId) return;

    try {
      await fetch(
        `/api/v1/settings/${schoolId}/grading/tasks/${taskId}/`,
        { method: 'DELETE' }
      );
      setLoading(false);
      setTaskId(null);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div>
      <button onClick={() => updateGradingStyle('single_entry')}>
        Switch to Single Entry
      </button>
      
      {loading && (
        <div>
          <p>Processing: {progress}%</p>
          <progress value={progress} max="100" />
          <button onClick={cancelTask}>Cancel</button>
        </div>
      )}
      
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
    </div>
  );
}
```

### Vue Example

```vue
<template>
  <div>
    <button @click="updateGradingStyle('single_entry')">
      Switch to Single Entry
    </button>
    
    <div v-if="loading">
      <p>Processing: {{ progress }}%</p>
      <progress :value="progress" max="100"></progress>
      <button @click="cancelTask">Cancel</button>
    </div>
    
    <p v-if="error" style="color: red">Error: {{ error }}</p>
  </div>
</template>

<script>
export default {
  props: ['schoolId'],
  data() {
    return {
      loading: false,
      progress: 0,
      error: null,
      taskId: null,
      pollInterval: null
    };
  },
  methods: {
    async updateGradingStyle(newStyle) {
      this.loading = true;
      this.error = null;
      this.progress = 0;

      try {
        const response = await fetch(
          `/api/v1/settings/${this.schoolId}/grading/`,
          {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              grading_style: newStyle,
              force: true
            })
          }
        );

        const data = await response.json();

        if (data.is_async) {
          this.taskId = data.task_id;
          this.pollStatus();
        } else {
          this.loading = false;
          this.progress = 100;
          alert('Grading style updated successfully!');
        }
      } catch (err) {
        this.error = err.message;
        this.loading = false;
      }
    },

    pollStatus() {
      this.pollInterval = setInterval(async () => {
        try {
          const response = await fetch(
            `/api/v1/settings/${this.schoolId}/grading/tasks/${this.taskId}/`
          );
          const task = await response.json();

          this.progress = task.progress;

          if (task.status === 'completed') {
            clearInterval(this.pollInterval);
            this.loading = false;
            this.progress = 100;
            alert('Grading style updated successfully!');
          } else if (task.status === 'failed') {
            clearInterval(this.pollInterval);
            this.loading = false;
            this.error = task.error;
          }
        } catch (err) {
          clearInterval(this.pollInterval);
          this.error = err.message;
          this.loading = false;
        }
      }, 2000);
    },

    async cancelTask() {
      if (!this.taskId) return;

      try {
        await fetch(
          `/api/v1/settings/${this.schoolId}/grading/tasks/${this.taskId}/`,
          { method: 'DELETE' }
        );
        clearInterval(this.pollInterval);
        this.loading = false;
        this.taskId = null;
      } catch (err) {
        this.error = err.message;
      }
    }
  },
  beforeUnmount() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
    }
  }
};
</script>
```

---

## Best Practices

### 1. Always Poll with Delay
```javascript
// ✅ Good
await new Promise(resolve => setTimeout(resolve, 2000));

// ❌ Bad - hammers the server
while (true) { await checkStatus(); }
```

### 2. Handle All Status States
```javascript
switch (task.status) {
  case 'pending':
    // Show "queued" message
    break;
  case 'processing':
    // Show progress bar
    break;
  case 'completed':
    // Show success
    break;
  case 'failed':
    // Show error
    break;
  case 'cancelled':
    // Show cancelled message
    break;
}
```

### 3. Set Timeouts
```javascript
const timeout = setTimeout(() => {
  clearInterval(pollInterval);
  setError('Task timeout - taking too long');
}, 300000); // 5 minutes
```

### 4. Clean Up Intervals
```javascript
useEffect(() => {
  return () => {
    if (pollInterval) {
      clearInterval(pollInterval);
    }
  };
}, [pollInterval]);
```

---

## Testing

### Manual Testing with cURL

```bash
# 1. Update grading style
RESPONSE=$(curl -X PATCH "http://localhost:8000/api/v1/settings/school123/grading/" \
  -H "Content-Type: application/json" \
  -d '{"grading_style": "single_entry", "force": true}')

echo $RESPONSE

# 2. Extract task_id (if async)
TASK_ID=$(echo $RESPONSE | jq -r '.task_id')

# 3. Poll status
while true; do
  STATUS=$(curl "http://localhost:8000/api/v1/settings/school123/grading/tasks/$TASK_ID/")
  echo $STATUS | jq .
  
  TASK_STATUS=$(echo $STATUS | jq -r '.status')
  
  if [ "$TASK_STATUS" = "completed" ] || [ "$TASK_STATUS" = "failed" ]; then
    break
  fi
  
  sleep 2
done
```

---

## Summary

The GradingTaskStatusView provides:
- ✅ Real-time progress tracking
- ✅ Automatic settings update on completion
- ✅ Task cancellation support
- ✅ Clear error messages
- ✅ School-specific task isolation
- ✅ Simple polling interface

Perfect for long-running gradebook operations!
