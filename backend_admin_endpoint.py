# ENDPOINT SEGURO PARA ADMIN DELETE
# Agrega esto a tu archivo de backend (server.py, app.py, etc.)

from flask import Flask, request, jsonify
from supabase import create_client, Client
import os

app = Flask(__name__)

# Configuración de Supabase con SERVICE ROLE KEY (segura en backend)
SUPABASE_URL = "https://povaakggggoeewgqfyot.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBvdmFha2dnZ2dvZWV3Z3FmeW90Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjEyMzM4MywiZXhwIjoyMDg3Njk5MzgzfQ.zBwW-M-0S3IsPn8SepkXm7OalXGL6NovsqVriZzBXDQ"

# Cliente de Supabase con service role key
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

@app.route('/api/admin/delete-seleccion', methods=['DELETE'])
def delete_seleccion():
    try:
        # Obtener token del header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Token no proporcionado'}), 401
        
        token = auth_header.split(' ')[1]
        
        # Verificar token y obtener usuario
        try:
            # Decodificar token JWT para obtener email sin consultar tabla users
            import jwt
            decoded_token = jwt.decode(token, options={"verify_signature": False})
            user_email = decoded_token.get('email')
            
            if user_email != 'greenday_115@hotmail.com':
                return jsonify({'error': 'No autorizado - Solo admin'}), 403
        except Exception as jwt_error:
            return jsonify({'error': 'Token inválido'}), 401
        
        # Obtener datos del body
        data = request.get_json()
        user_id = data.get('userId')
        jornada = data.get('jornada')
        
        if not user_id or not jornada:
            return jsonify({'error': 'Faltan userId y jornada'}), 400
        
        # Ejecutar delete con service role key (ignora RLS)
        result = supabase_admin.table('selecciones').delete().eq('user_id', user_id).eq('jornada', jornada).execute()
        
        if hasattr(result, 'error') and result.error:
            return jsonify({'error': str(result.error)}), 500
        
        return jsonify({'success': True, 'message': 'Selección borrada correctamente'})
        
    except Exception as e:
        return jsonify({'error': f'Error del servidor: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
