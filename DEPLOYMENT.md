1. Install Python 3.10

2. Copy diode-flow folder

3. Run:

   chmod +x *.sh

4. Install dependencies:

   ./install_offline.sh

5. Launch UI:

   ./start_ui.sh

6. Open browser:

   http://localhost:8501

7. Start receiver node:

   ./start_receiver.sh

8. Start transfer:

   - Open UI
   - Enter file path
   - Select security level
   - Configure PPS
   - Configure packet loss simulation (optional)
   - Optional BLAKE3 key
   - Click Start Transfer

9. Reconstructed files appear in:

   demo_output/storage/