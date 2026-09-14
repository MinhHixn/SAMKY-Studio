import os
import json
import subprocess
import sys

def main():
    backend_dir = r"c:\Users\TPGHien\Desktop\Claw-4-FUN\MiroFish-Offline\backend"
    test_run_dir = os.path.join(backend_dir, "test_run")
    os.makedirs(test_run_dir, exist_ok=True)
    
    # 1. Create a minimal simulation_config.json
    config = {
      "simulation_id": "local_openrouter_test",
      "event_id": "C1_test",
      "event_question": "Which party will win the 2024 US Presidential Election?",
      "truth": "Republican",
      "time_config": {
        "total_simulation_hours": 2,
        "minutes_per_round": 60,
        "agents_per_hour_min": 10,
        "agents_per_hour_max": 20,
        "off_peak_activity_multiplier": 1.0,
        "peak_activity_multiplier": 1.0
      },
      "agent_configs": [
        {
          "agent_id": 0,
          "entity_name": "Agent Zero",
          "entity_uuid": "context-0-0",
          "entity_type": "person",
          "activity_level": 1.0,
          "active_hours": [],
          "name": "Political Analyst #0",
          "username": "context_0_0",
          "bio": "Data-driven political analyst observing macro trends and election outcomes.",
          "persona": "- Worldview: Empirical and data-driven.\n- Motivation: To accurately forecast shifts in power.\n- Style: Professional and objective.\n- Biases: Triggered by emotional or unsubstantiated claims.\n- Global Language Rule: Speak and post strictly in English only.",
          "source_seed_file": "intelligent_generation"
        },
        {
          "agent_id": 1,
          "entity_name": "Agent One",
          "entity_uuid": "context-0-1",
          "entity_type": "person",
          "activity_level": 1.0,
          "active_hours": [],
          "name": "Donald Jr. #1",
          "username": "donald_jr._1",
          "bio": "Heir to the Trump name and business empire.",
          "persona": "- Worldview:  Practical Realist\n- Motivation:  Expand family legacy\n- Style:  Commanding\n- Biases & Triggers:  Dislike of political opposition\n- Global Language Rule: Speak and post strictly in English only.",
          "source_seed_file": "intelligent_generation"
        }
      ]
    }
    
    config_path = os.path.join(test_run_dir, "simulation_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"Created config: {config_path}")
    
    # 2. Create reddit_profiles.json
    reddit_profiles = [
      {
        "user_id": 0,
        "username": "context_0_0",
        "name": "Political Analyst #0",
        "bio": "Data-driven political analyst observing macro trends and election outcomes.",
        "persona": "- Worldview: Empirical and data-driven.\n- Motivation: To accurately forecast shifts in power.\n- Style: Professional and objective.\n- Biases: Triggered by emotional or unsubstantiated claims.\n- Global Language Rule: Speak and post strictly in English only.",
        "karma": 1000,
        "created_at": "2026-05-26",
        "age": 30,
        "gender": "other",
        "mbti": "ISTJ",
        "country": "US",
        "profession": "Analyst",
        "interested_topics": []
      },
      {
        "user_id": 1,
        "username": "donald_jr._1",
        "name": "Donald Jr. #1",
        "bio": "Heir to the Trump name and business empire.",
        "persona": "- Worldview:  Practical Realist\n- Motivation:  Expand family legacy\n- Style:  Commanding\n- Biases & Triggers:  Dislike of political opposition\n- Global Language Rule: Speak and post strictly in English only.",
        "karma": 3678,
        "created_at": "2024-01-01",
        "age": 39,
        "gender": "male",
        "mbti": "ENTJ",
        "country": "USA",
        "profession": "Businessman",
        "interested_topics": ["Real Estate"]
      }
    ]
    
    reddit_profiles_path = os.path.join(test_run_dir, "reddit_profiles.json")
    with open(reddit_profiles_path, "w", encoding="utf-8") as f:
        json.dump(reddit_profiles, f, indent=2, ensure_ascii=False)
    print(f"Created reddit profiles: {reddit_profiles_path}")
    
    # 3. Create twitter_profiles.csv
    twitter_profiles_path = os.path.join(test_run_dir, "twitter_profiles.csv")
    with open(twitter_profiles_path, "w", encoding="utf-8") as f:
        f.write("user_id,name,username,user_char,description\n")
        f.write("0,Political Analyst #0,context_0_0,Worldview: Empirical and data-driven. Motivation: To accurately forecast shifts in power. Style: Professional and objective. Biases: Triggered by emotional or unsubstantiated claims.,Data-driven political analyst observing macro trends and election outcomes.\n")
        f.write("1,Donald Jr. #1,donald_jr._1,Worldview: Practical Realist. Motivation: Expand family legacy. Style: Commanding. Biases & Triggers: Dislike of political opposition.,Heir to the Trump name and business empire.\n")
    print(f"Created twitter profiles: {twitter_profiles_path}")
    
    # 4. Invoke parallel simulation runner
    python_exe = os.path.join(backend_dir, ".venv311", "Scripts", "python.exe")
    script_path = os.path.join(backend_dir, "scripts", "run_parallel_simulation.py")
    
    print("\nStarting local simulation test. Executing...")
    cmd = [python_exe, script_path, "--config", config_path]
    print(f"Command: {' '.join(cmd)}")
    
    # Run process
    process = subprocess.Popen(
        cmd,
        cwd=backend_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1
    )
    
    # Print output in real-time
    for line in process.stdout:
        print(line, end="")
        
    process.wait()
    print(f"\nSimulation process finished with code: {process.returncode}")

if __name__ == "__main__":
    main()
