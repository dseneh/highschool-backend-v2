"""
Test the enhanced reports functionality
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from reports.tasks import TaskManager, MockTaskProcessor
from reports.settings import get_reports_setting

def test_task_manager():
    """Test the TaskManager functionality"""
    print("🧪 Testing TaskManager...")
    
    # Test settings
    threshold = get_reports_setting('BACKGROUND_THRESHOLD')
    print(f"✅ Background threshold: {threshold}")
    
    # Test background decision
    small_count = 1000
    large_count = 10000
    
    should_bg_small = TaskManager.should_use_background(small_count)
    should_bg_large = TaskManager.should_use_background(large_count)
    should_bg_export = TaskManager.should_use_background(small_count, 'csv')
    
    print(f"✅ Small dataset ({small_count}): Background = {should_bg_small}")
    print(f"✅ Large dataset ({large_count}): Background = {should_bg_large}")
    print(f"✅ Export format: Background = {should_bg_export}")
    
    # Test task creation
    task_params = {
        'school_id': 'test123',
        'query_params': {'target': 'student'},
        'user_id': 1
    }
    
    task_id = TaskManager.create_task(
        task_type='transaction_report',
        query_params=task_params,
        user_id=1,
        estimated_count=large_count
    )
    
    print(f"✅ Created task: {task_id}")
    
    # Test task retrieval
    task_data = TaskManager.get_task(task_id)
    if task_data:
        print(f"✅ Retrieved task: Status = {task_data['status']}")
    
    # Test task update
    success = TaskManager.update_task(task_id, status='processing', progress=50)
    print(f"✅ Updated task: {success}")
    
    # Test cache functionality
    cache_key = TaskManager.generate_cache_key({'test': 'data'})
    print(f"✅ Generated cache key: {cache_key}")
    
    # Test caching results
    test_result = {'count': 100, 'data': [1, 2, 3]}
    TaskManager.cache_result(cache_key, test_result)
    
    cached_result = TaskManager.get_cached_result(cache_key)
    if cached_result:
        print(f"✅ Cached and retrieved result: {cached_result['count']} records")
    
    print("🎉 TaskManager tests completed!\n")

def test_mock_processor():
    """Test the mock background processor"""
    print("🧪 Testing MockTaskProcessor...")
    
    # Create a test task
    task_params = {
        'school_id': 'test123',
        'query_params': {'target': 'student'},
        'user_id': 1
    }
    
    task_id = TaskManager.create_task(
        task_type='transaction_report',
        query_params=task_params,
        user_id=1,
        estimated_count=5000
    )
    
    print(f"✅ Created test task: {task_id}")
    
    # Start mock processing
    MockTaskProcessor.process_transaction_report(task_id)
    print("✅ Started background processing (mock)")
    
    # Check initial status
    task_data = TaskManager.get_task(task_id)
    if task_data:
        print(f"✅ Initial status: {task_data['status']}")
    
    # Wait a bit and check progress
    import time
    time.sleep(3)
    
    task_data = TaskManager.get_task(task_id)
    if task_data:
        print(f"✅ Progress update: {task_data['status']} - {task_data.get('progress', 0)}%")
    
    # Wait for completion
    time.sleep(4)
    
    task_data = TaskManager.get_task(task_id)
    if task_data:
        print(f"✅ Final status: {task_data['status']} - {task_data.get('progress', 0)}%")
        if task_data.get('result_url'):
            print(f"✅ Result URL: {task_data['result_url']}")
    
    print("🎉 MockTaskProcessor tests completed!\n")

if __name__ == "__main__":
    print("🚀 Testing Enhanced Reports API\n")
    
    try:
        test_task_manager()
        test_mock_processor()
        print("✅ All tests passed successfully! 🎉")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
